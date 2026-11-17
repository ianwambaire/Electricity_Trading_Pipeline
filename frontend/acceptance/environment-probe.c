/* macOS-only, current-process key-name probe. Never reads past '=' or emits values. */
#include <stdio.h>
#include <string.h>
#include <crt_externs.h>
#ifdef PROBE_COREFOUNDATION
#include <CoreFoundation/CoreFoundation.h>
/* Force linkage only; no CoreFoundation function is invoked by this program. */
__attribute__((used)) static CFTypeID (*const bound_cf_symbol)(CFTypeRef) = CFGetTypeID;
#endif
static const char *safe_names[] = {
  "PATH", "TMPDIR", "LANG", "__CF_USER_TEXT_ENCODING", "LC_CTYPE", "LC_ALL",
  "TERM", "PWD", "SHLVL", "_", "NODE_OPTIONS", "NODE_PATH", "DEBUG", "PWDEBUG"
};
static int same_key(const char *entry, const char *key) {
  size_t length = strlen(key); /* key is a fixed public identifier, never an entry */
  return strncmp(entry, key, length) == 0 && entry[length] == '=';
}
int main(int argc, char **argv) {
  (void)argv;
  if (argc != 1) { puts("{\"status\":\"UNEXPECTED_ARGUMENTS\"}"); return 2; }
  char **entries = *_NSGetEnviron();
  int present[sizeof(safe_names)/sizeof(safe_names[0])] = {0};
  size_t redacted = 0;
  for (size_t i=0; entries[i] != NULL; i++) {
    int recognized = 0;
    for (size_t k=0; k<sizeof(safe_names)/sizeof(safe_names[0]); k++) {
      if (same_key(entries[i], safe_names[k])) { present[k]=1; recognized=1; break; }
    }
    if (!recognized) redacted++;
  }
  printf("{\"boundary\":\"native-entry\",\"observedSafeKeys\":[");
  int comma=0;
  for (size_t k=0; k<sizeof(safe_names)/sizeof(safe_names[0]); k++) {
    if (present[k]) { printf("%s\"%s\"", comma?",":"",safe_names[k]); comma=1; }
  }
  printf("],\"redactedKeyCount\":%zu}\n",redacted);
  return 0;
}
