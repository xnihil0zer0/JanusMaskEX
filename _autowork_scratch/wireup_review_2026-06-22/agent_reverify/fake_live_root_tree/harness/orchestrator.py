def real_collaborator():
    # the WATCHED symbol -- a real top-level callable that the live root
    # invokes directly on the production path. (Models e.g. smoke_import.)
    return 'real work'

def other_collaborator():
    return None

def live_root_iter(collab_real, collab_other):
    # production body: it calls BOTH collaborators DIRECTLY.
    collab_other()
    return collab_real()
