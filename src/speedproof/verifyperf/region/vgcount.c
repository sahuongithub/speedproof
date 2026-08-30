/* Client-request shim so a Python workload can mark the region to be counted.
 *
 * Callgrind exposes its controls as magic instruction sequences rather than as
 * a callable library, so they cannot be invoked from Python directly. This
 * wraps them in ordinary functions that ctypes can reach.
 *
 * Outside Valgrind the macros expand to no-ops, so a workload that imports the
 * shim still runs normally when nobody is counting.
 *
 * Build: gcc -O2 -fPIC -shared -o libvgcount.so vgcount.c
 */
#include <valgrind/callgrind.h>
#include <valgrind/valgrind.h>

void vgcount_zero(void)   { CALLGRIND_ZERO_STATS; }
void vgcount_start(void)  { CALLGRIND_START_INSTRUMENTATION; }
void vgcount_stop(void)   { CALLGRIND_STOP_INSTRUMENTATION; }
void vgcount_dump(void)   { CALLGRIND_DUMP_STATS; }
int  vgcount_active(void) { return RUNNING_ON_VALGRIND ? 1 : 0; }
