# Minimal pure-Python cytoolz stub for Android / Buildozer
# Satisfies eth-account 0.10.0 without any compiled extensions

def dissoc(d, *keys):
    """Return a new dict with the given keys removed."""
    return {k: v for k, v in d.items() if k not in keys}

def assoc(d, key, value):
    """Return a new dict with key set to value."""
    result = dict(d)
    result[key] = value
    return result

def merge(*dicts):
    result = {}
    for d in dicts:
        result.update(d)
    return result

def get_in(keys, coll, default=None):
    for key in keys:
        try:
            coll = coll[key]
        except (KeyError, TypeError, IndexError):
            return default
    return coll

# Add any other names that may be imported
identity = lambda x: x
