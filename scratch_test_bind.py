import inspect

def test_fn(a, /, b, *, c):
    print("test_fn called with:", a, b, c)

def bind_arguments(fn, kwargs):
    sig = inspect.signature(fn)
    args = []
    bound_kwargs = {}
    
    for name, param in sig.parameters.items():
        if param.kind == inspect.Parameter.POSITIONAL_ONLY:
            if name in kwargs:
                args.append(kwargs[name])
        elif param.kind == inspect.Parameter.POSITIONAL_OR_KEYWORD:
            if name in kwargs:
                args.append(kwargs[name])
        elif param.kind == inspect.Parameter.KEYWORD_ONLY:
            if name in kwargs:
                bound_kwargs[name] = kwargs[name]
        elif param.kind == inspect.Parameter.VAR_POSITIONAL:
            pass
        elif param.kind == inspect.Parameter.VAR_KEYWORD:
            for k, v in kwargs.items():
                if k not in sig.parameters:
                    bound_kwargs[k] = v
                    
    return args, bound_kwargs

try:
    kwargs = {"a": 1, "b": 2, "c": 3}
    args, b_kwargs = bind_arguments(test_fn, kwargs)
    print("args:", args)
    print("b_kwargs:", b_kwargs)
    test_fn(*args, **b_kwargs)
except Exception as e:
    print("Error:", type(e), e)
