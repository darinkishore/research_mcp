import multiprocessing

import dspy

DEFAULT_WORKERS = min(multiprocessing.cpu_count() * 2, 32)

# Initialize DSPy with GPT-4
_lm = None


def get_dspy_lm(async_max_workers: int = DEFAULT_WORKERS):
    global _lm
    if _lm is None:
        _lm = dspy.LM('openai/gpt-4o-2024-11-20')
        dspy.settings.configure(lm=_lm, async_max_workers=async_max_workers)
    return _lm
