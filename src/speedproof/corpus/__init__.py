"""Building a corpus of real optimisations from repository history.

A task is a pair of commits from a real project: the state before a
performance change a human made, and the change itself. The repository's own
benchmark suite supplies the workload and its own tests supply correctness, so
nothing about the task is authored here — which is the point, because a
benchmark whose author also wrote the answer is measuring itself.
"""

from speedproof.corpus.task import Task, in_scope, load_tasks

__all__ = ["Task", "in_scope", "load_tasks"]
