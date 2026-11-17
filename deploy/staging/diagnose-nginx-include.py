#!/usr/bin/env python3
"""Approval required: bounded include-only diagnostic, never expands rejected paths."""
import fnmatch
import glob
import hashlib
import json
import os
from pathlib import Path
import re
import shlex

TARGET = Path('/etc/nginx/conf.d/powerflow-staging-https.conf')
MAX_FILES, MAX_FILE_BYTES, MAX_TOTAL_BYTES = 32, 65536, 524288


def include_lines(text):
    """Independent source-line annotation; does not output source contents."""
    result, word, first = [], [], True
    quote, escaped, comment = None, False, False
    line, start = 1, None
    def flush():
        nonlocal first, word, start
        if word:
            if first and ''.join(word) == 'include': result.append(start)
            first = False
            word, start = [], None
    for char in text:
        if comment:
            if char == '\n': comment = False; line += 1
            continue
        if escaped:
            if start is None: start = line
            if char != '\n': word.append(char)
            else: line += 1
            escaped = False
            continue
        if char == '\\' and quote != "'":
            if start is None: start = line
            escaped = True
            continue
        if quote:
            if char == quote: quote = None
            else: word.append(char)
            if char == '\n': line += 1
            continue
        if char in ('"', "'"):
            if start is None: start = line
            quote = char
        elif char == '#':
            flush(); comment = True
        elif char in '{};':
            flush(); first = True
        elif char.isspace():
            flush()
            if char == '\n': line += 1
        else:
            if start is None: start = line
            word.append(char)
    flush()
    if quote or escaped: raise ValueError('source_annotation_incomplete')
    return result


def safe_pattern(value):
    # Only filesystem-pattern characters; never print arbitrary URI/credential tokens.
    if re.fullmatch(r'[A-Za-z0-9_./*?\[\]+-]+', value): return value
    return '[REDACTED_NON_PATH_TOKEN sha256=' + hashlib.sha256(value.encode()).hexdigest() + ']'


def inspect(config_root=Path('/etc/nginx'), target=TARGET):
    allowed = [config_root, Path('/usr/share/nginx/modules'), Path('/usr/lib64/nginx/modules')]
    cache, stack, edges, failures, sites, files = {}, [], [], [], [], []
    directive_count = [0]
    errors = []

    def load(path, context=(), hierarchy=()):
        path = Path(path); real = path.resolve()
        if not any(base in real.parents for base in allowed): raise ValueError('unapproved_include_root')
        if len(stack) >= 8 or real in stack: raise ValueError('include_cycle_or_depth')
        if real not in cache:
            if len(cache) >= MAX_FILES: raise ValueError('configuration_count_limit')
            if not real.is_file() or real.is_symlink(): raise ValueError('configuration_file_type')
            if real.stat().st_size > MAX_FILE_BYTES: raise ValueError('configuration_file_size')
            raw = real.read_bytes()
            if sum(len(v) for v in cache.values()) + len(raw) > MAX_TOTAL_BYTES:
                raise ValueError('configuration_bytes_limit')
            cache[real] = raw
            files.append(str(real))
        text = cache[real].decode()
        lines = include_lines(text)
        lex = shlex.shlex(text, posix=True, punctuation_chars='{};')
        lex.whitespace_split = True; lex.commenters = '#'
        tokens = []
        for token in lex:
            if token and set(token) <= set('{};'): tokens.extend(token)
            else: tokens.append(token)
        index, include_index = [0], [0]
        stack.append(real)

        def parse(ctx, nested=False):
            while index[0] < len(tokens):
                if tokens[index[0]] == '}':
                    if not nested: raise ValueError('unexpected_closing_brace')
                    index[0] += 1
                    return
                words = []
                while index[0] < len(tokens) and tokens[index[0]] not in '{};':
                    words.append(tokens[index[0]]); index[0] += 1
                if not words or index[0] >= len(tokens): raise ValueError('unsupported_configuration_syntax')
                end = tokens[index[0]]; index[0] += 1
                if end not in (';', '{'): raise ValueError('invalid_directive_end')
                directive_count[0] += 1
                if directive_count[0] > 4096: raise ValueError('expanded_directive_limit')
                name, args = words[0], words[1:]
                if name == 'include':
                    if include_index[0] >= len(lines): raise ValueError('include_line_annotation_mismatch')
                    number = lines[include_index[0]]; include_index[0] += 1
                    entry = {'source_file': str(real), 'line': number,
                             'context': [v if v in ('http', 'server', 'location', 'events', 'types', 'stream', 'mail')
                                         else '[other block]' for v in ctx],
                             'pattern': safe_pattern(args[0]) if len(args) == 1 else '[invalid argument count]',
                             'include_hierarchy': list(hierarchy)}
                    code = None
                    pattern = None
                    if end != ';' or len(args) != 1 or '$' in args[0]:
                        code = 'unsupported_include'
                    else:
                        pattern = Path(args[0])
                        if not pattern.is_absolute(): pattern = config_root / pattern
                        entry['reviewer_normalized_pattern'] = safe_pattern(str(pattern))
                        if '..' in pattern.parts: code = 'include_parent_traversal'
                        elif not any(base in pattern.parents for base in allowed): code = 'unapproved_include_pattern'
                        elif any(c in str(pattern.parent) for c in '*?['): code = 'wildcard_include_directory'
                    entry['reviewer_result'] = code or 'ACCEPTED_PATTERN'
                    if code:
                        entry['expansion'] = 'NOT_EXPANDED'
                        edges.append(entry); failures.append(dict(entry))
                        # Continue other approved includes solely for this diagnostic.
                        if end == '{': raise ValueError('invalid_include_block')
                        continue
                    if pattern.parent == target.parent and fnmatch.fnmatchcase(target.name, pattern.name):
                        sites.append({'source_file': str(real), 'line': number,
                                      'context': entry['context'], 'pattern': entry['pattern']})
                    matches = sorted(glob.glob(str(pattern)))
                    if len(matches) > 32: raise ValueError('include_match_limit')
                    entry['matched_files'] = matches
                    edges.append(entry)
                    branch = (*hierarchy, {'source_file': str(real), 'line': number,
                                           'pattern': entry['pattern']})
                    for match in matches:
                        try: load(match, ctx, branch)
                        except (OSError, ValueError, UnicodeError) as error:
                            errors.append({'source_file': str(real), 'line': number,
                                           'error': str(error) if isinstance(error, ValueError) else 'include_read_failed'})
                elif end == '{': parse(ctx + (name,), True)
            if nested: raise ValueError('unclosed_block')

        try:
            parse(context)
            if include_index[0] != len(lines): raise ValueError('include_line_annotation_mismatch')
        finally: stack.pop()

    try: load(config_root / 'nginx.conf')
    except (OSError, ValueError, UnicodeError) as error:
        errors.append({'error': str(error) if isinstance(error, ValueError) else 'configuration_read_failed'})
    return {
        'status': 'complete' if not errors else 'incomplete',
        'source_files_read': files,
        'include_directives': edges,
        'first_rejected_include_observed': failures[0] if failures else None,
        'additional_rejected_includes': failures[1:],
        'staging_https_target': str(target),
        'potential_installation_include_sites': sites,
        'one_observed_http_include_site': len(sites) == 1 and sites[0]['context'] == ['http'],
        'all_include_branches_reviewed': not failures and not errors,
        'errors': errors,
        'limitations': [
            'No rejected pattern is expanded or read',
            'Other approved branches are inspected after a rejection; activation would have stopped',
            'Line annotations use a separate scanner; detected mismatches are reported as incomplete',
            'Token review is not authoritative Nginx parsing or proof of loaded configuration',
            'Uninspected branches can contain additional configuration or conflicts',
            'Runtime Nginx prefix/configuration command-line options are not inspected',
        ],
    }


def main():
    if os.geteuid() != 0:
        print(json.dumps({'status': 'failed', 'error': 'noninteractive_sudo_root_required'}))
        return 1
    report = inspect()
    print(json.dumps(report, indent=2))
    return 0 if report['status'] == 'complete' else 1


if __name__ == '__main__': raise SystemExit(main())
