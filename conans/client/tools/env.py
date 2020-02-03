import os
import sys
from contextlib import contextmanager

from conans.client.run_environment import RunEnvironment
from conans.client.tools.files import _path_equals, which
from conans.errors import ConanException


@contextmanager
def pythonpath(conanfile):
    python_path = conanfile.env.get("PYTHONPATH", None)
    if python_path:
        old_path = sys.path[:]
        if isinstance(python_path, list):
            sys.path.extend(python_path)
        else:
            sys.path.append(python_path)

        yield
        sys.path = old_path
    else:
        yield


@contextmanager
def run_environment(conanfile):
    with environment_append(RunEnvironment(conanfile).vars):
        yield


@contextmanager
def environment_append(env_vars):
    with _environment_add(env_vars, post=False):
        yield


@contextmanager
def _environment_add(env_vars, post=False):
    """
    :param env_vars: List (dict) of simple environment vars. {name: value, name2: value2}
                     => e.g.: MYVAR=1
                     The values can also be lists of appendable environment vars.
                     {name: [value, value2]} => e.g. PATH=/path/1:/path/2
                     If the value is set to None, then that environment variable is unset.
    :param post: if True, the environment is appended at the end, not prepended (only LISTS)
    :return: None
    """
    if not env_vars:
        yield
        return

    unset_vars = []
    apply_vars = {}
    for name, value in env_vars.items():
        if value is None:
            unset_vars.append(name)
        elif isinstance(value, list):
            apply_vars[name] = os.pathsep.join(value)
            old = os.environ.get(name)
            if old:
                if post:
                    apply_vars[name] = old + os.pathsep + apply_vars[name]
                else:
                    apply_vars[name] += os.pathsep + old
        else:
            apply_vars[name] = value

    old_env = dict(os.environ)
    os.environ.update(apply_vars)
    for var in unset_vars:
        os.environ.pop(var, None)
    try:
        yield
    finally:
        os.environ.clear()
        os.environ.update(old_env)


@contextmanager
def no_op():
    yield


@contextmanager
def remove_from_path(command):
    curpath = os.getenv("PATH")
    first_it = True
    for _ in range(30):
        if not first_it:
            with environment_append({"PATH": curpath}):
                the_command = which(command)
        else:
            the_command = which(command)
            first_it = False

        if not the_command:
            break
        new_path = []
        for entry in curpath.split(os.pathsep):
            if not _path_equals(entry, os.path.dirname(the_command)):
                new_path.append(entry)

        curpath = os.pathsep.join(new_path)
    else:
        raise ConanException("Error in tools.remove_from_path!! couldn't remove the tool '%s' "
                             "from the path after 30 attempts, still found in '%s' this is a "
                             "Conan client bug, please open an issue at: "
                             "https://github.com/conan-io/conan\n\nPATH=%s"
                             % (command, the_command, os.getenv("PATH")))

    with environment_append({"PATH": curpath}):
        yield
