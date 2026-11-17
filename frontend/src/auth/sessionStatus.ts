// Non-sensitive, in-memory status used to explain an ended session.
let ended = false
export function markSessionEnded(): void { ended = true }
export function clearSessionEnded(): void { ended = false }
export function sessionHasEnded(): boolean { return ended }
