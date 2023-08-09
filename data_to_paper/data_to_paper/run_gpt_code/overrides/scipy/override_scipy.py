import functools

import scipy

from data_to_paper.run_gpt_code.overrides.attr_replacers import func_replacer
from data_to_paper.run_gpt_code.overrides.statsmodels.pvalue_dtype import PValueDtype, PValueFloat

import inspect


def scipy_label_pvalues():
    """
    A context manager that replaces the pvalues attribute of all scipy hypothesis test functions with a
    PValueDtype.
    """
    def should_replace_func(module, func_name):
        obj = getattr(module, func_name)
        doc = inspect.getdoc(obj)
        if doc and "p-value" in doc:
            return True
        return False

    def fit_wrapper(original_func):
        @functools.wraps(original_func)
        def wrapped(*args, **kwargs):
            result = original_func(*args, **kwargs)

            # Replace the pvalues attribute if it exists
            try:
                asdict = {k.strip('_'): v for k, v in result._asdict().items()}
                if 'pvalue' in asdict:
                    asdict['pvalue'] = PValueFloat(asdict['pvalue'])
                    result = type(result)(**asdict)
            except (AttributeError, TypeError, ValueError):
                pass
            return result
        wrapped.is_wrapped = True
        return wrapped

    return func_replacer(scipy, fit_wrapper, should_replace_func)
