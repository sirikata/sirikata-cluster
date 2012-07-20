#!/usr/bin/env python

def parse_or_die(cmd, types, *args, **kwargs):
    '''"Parse" the positional arguments, ensuring there are the
    correct number and casting to the right types, then return them as
    a tuple.

    The first parameters should be a command name to indicated where
    errors are originating.  The second parameter should be a list of
    types for casting, e.g. [str, str, int].

    If you add rest=True, any leftover arguments won't cause an error
    and will be returned as list as an extra item in the returned list
    of arguments.
    '''

    return_rest = ('rest' in kwargs and kwargs['rest'])

    if len(args) < len(types):
        print "Too few parameters. Command help:"
        print
        print cmd.__doc__
        exit(1)
    if len(args) != len(types) and not return_rest:
        print "Too many parameters. Command help:"
        print
        print cmd.__doc__
        exit(1)

    args_out = []
    for idx,typ,arg in zip(range(len(types)),types,args[0:len(types)]):
        try:
            if typ == object:
                args_out.append(arg)
            else:
                args_out.append( typ(arg) )
        except:
            print "Couldn't convert argument %d (%s) to %s" % (idx, arg, typ)
            exit(1)

    rest_args = args[len(types):]
    if return_rest: args_out.append(rest_args)

    if len(args_out) == 1:
        return args_out[0]
    return tuple(args_out)
