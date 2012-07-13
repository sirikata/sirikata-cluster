#!/usr/bin/env python

def parse_or_die(cmd, types, *args):
    '''"Parse" the positional arguments, ensuring there are the
    correct number and casting to the right types, then return them as
    a tuple.

    The first parameters should be a command name to indicated where
    errors are originating.  The second parameter should be a list of
    types for casting, e.g. [str, str, int].
    '''

    if len(args) != len(types):
        print "Incorrect parameters for '%s'" % (cmd)
        exit(1)

    args_out = []
    for idx,typ,arg in zip(range(len(types)),types,args):
        try:
            args_out.append( typ(arg) )
        except:
            print "Couldn't convert argument %d (%s) to %s" % (idx, arg, typ)
            exit(1)

    if len(args_out) == 1:
        return args_out[0]
    return tuple(args_out)
