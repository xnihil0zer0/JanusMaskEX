from __future__ import annotations
import inspect
import traceback
from typing import Any, Callable
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

def _fuzz_one(fn: Callable[..., Any], name: str, strategies: dict[str, st.SearchStrategy[Any]], timeout: float) -> str | None:
    def bind_arguments(func: Callable[..., Any], kwargs: dict[str, Any]) -> tuple[list[Any], dict[str, Any]]:
        try:
            sig = inspect.signature(func)
        except Exception:
            return [], kwargs
            
        args = []
        bound_kwargs = {}
        
        for name_param, param in sig.parameters.items():
            if param.kind == inspect.Parameter.POSITIONAL_ONLY:
                if name_param in kwargs:
                    args.append(kwargs[name_param])
                elif param.default is not inspect.Parameter.empty:
                    args.append(param.default)
            elif param.kind == inspect.Parameter.POSITIONAL_OR_KEYWORD:
                if name_param in kwargs:
                    bound_kwargs[name_param] = kwargs[name_param]
            elif param.kind == inspect.Parameter.KEYWORD_ONLY:
                if name_param in kwargs:
                    bound_kwargs[name_param] = kwargs[name_param]
            elif param.kind == inspect.Parameter.VAR_KEYWORD:
                for k, v in kwargs.items():
                    if k not in sig.parameters:
                        bound_kwargs[k] = v
            elif param.kind == inspect.Parameter.VAR_POSITIONAL:
                if name_param in kwargs:
                    val = kwargs[name_param]
                    if isinstance(val, (list, tuple)):
                        args.extend(val)
                    else:
                        args.append(val)
                        
        return args, bound_kwargs

    if not strategies:
        try:
            fn()
        except Exception as e:
            tb_str = "".join(traceback.format_exception(type(e), e, e.__traceback__))
            return (
                f"Fuzzing function {name} failed with {type(e).__name__}.\n"
                f"Traceback:\n{tb_str}"
            )
        return None

    def test_target(**kwargs):
        args, b_kwargs = bind_arguments(fn, kwargs)
        fn(*args, **b_kwargs)
        
    test_target.__name__ = name
    test_target.__qualname__ = name
    
    deadline_val = int(timeout * 1000) if timeout else None
    
    decorated = given(**strategies)(
        settings(
            max_examples=200,
            deadline=deadline_val,
            database=None,
            suppress_health_check=[
                HealthCheck.too_slow,
                HealthCheck.filter_too_much
            ]
        )(test_target)
    )
    
    try:
        decorated()
    except Exception as e:
        tb_str = "".join(traceback.format_exception(type(e), e, e.__traceback__))
        notes = getattr(e, '__notes__', [])
        notes_str = "\n".join(notes)
        return (
            f"Fuzzing function {name} failed with {type(e).__name__}.\n"
            f"Traceback:\n{tb_str}\n"
            f"Notes:\n{notes_str}"
        )
    return None
