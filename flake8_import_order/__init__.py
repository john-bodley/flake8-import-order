
try:
    import ast
except ImportError:
    from flake8.util import ast

from collections import defaultdict
import distutils.sysconfig as sysconfig
import imp
import itertools
import keyword
import os
import pkgutil
import re
import sys
import tokenize


def isidentifier(value):
    if value in keyword.kwlist:
        return False
    return re.match('^' + tokenize.Name + '$', value, re.I) is not None


def iter_stdlibs():
    """
    Find quite a lot of stdlib.
    Some things like os.path can't be found this way. You actually need to
    *run* Python code to fully expand all valid import statements, so
    instead we're just going to rely on getting most of them and then only
    matching on the root of import statements the rest of the time.
    """

    stdlib_path = sysconfig.get_python_lib(standard_lib=True)
    stdlib_paths = [
        path
        for path in sys.path
        if path.startswith(stdlib_path) and '-packages' not in path
    ]
    return (nm for _, nm, _ in pkgutil.iter_modules(stdlib_paths))


class ImportVisitor(ast.NodeVisitor):
    """
    This class visits all the import nodes at the root of tree
    and generates new import nodes that are sorted according to the Google
    and PEP8 coding guidelines.

    In practice this means that they are sorted according to this tuple.

        (stdlib, site_packages, names)

    We also make sure only 1 name is imported per import statement.
    """

    def __init__(self):
        self.original_nodes = []
        self.imports = []
        self.stdlibs = set(iter_stdlibs()) | set(sys.builtin_module_names)
        self.python_paths = [p for p in sys.path if p]

    def visit_Import(self, node):
        if node.col_offset != 0:
            return
        else:
            self.imports.append(node)
            return

            self.imports.append([
                ((node.level, None), (nm.name, nm.asname, node))
                for nm in node.names
            ])

    def visit_ImportFrom(self, node):
        # we need to group the names imported from each module
        # into single from X import N,M,P,... groups so we store the names
        # and regenerate the node when we find more
        # we'll then insert this into the full imports chain when we're done
        if node.col_offset != 0:
            return
        else:
            self.imports.append(node)
            return

            self.imports.append([
                ((node.level, node.module), (nm.name, nm.asname, node))
                for nm in node.names
            ])

    def node_sort_key(self, node):
        """
        Return a key that will sort the nodes in the correct
        order for the Google Code Style guidelines.
        """
        if isinstance(node, ast.Import):
            if node.names[0].asname:
                name = [node.names[0].name, node.names[0].asname]
            else:
                name = [node.names[0].name]
            from_names = None

        elif isinstance(node, ast.ImportFrom):
            name = [node.module]
            from_names = [nm.name for nm in node.names]
        else:
            raise TypeError(node)

        # stdlib, site package, name, is_fromimport, from_names
        key = [True, True, name, from_names]

        if not name[0]:
            key[2] = [node.level]
        else:
            name = [v.lower() for v in name]
            key[2] = name
            p = ast.parse(name[0])
            for n in ast.walk(p):
                if not isinstance(n, ast.Name):
                    continue

                if n.id in self.stdlibs:
                    key[0] = False
                else:
                    try:
                        key[1] = not imp.find_module(
                            n.id,
                            self.python_paths
                        )
                    except ImportError:
                        continue
        return key


def error(node, code, message):
    lineno, col_offset = node.lineno, node.col_offset

    if isinstance(node, ast.ClassDef):
        lineno += len(node.decorator_list)
        col_offset += 6
    elif isinstance(node, ast.FunctionDef):
        lineno += len(node.decorator_list)
        col_offset += 4

    return (lineno, col_offset, '{0} {1}'.format(code, message),
            ImportOrderChecker)


class ImportOrderChecker(object):
    name = "import-order"
    version = "0.1"

    def __init__(self, tree, filename):
        self.visitor = ImportVisitor()
        self.tree = tree

    def run(self):
        self.visitor.visit(self.tree)
        prev_node = None
        for node in self.visitor.imports:
            if node and prev_node:
                node_key = self.visitor.node_sort_key(node)
                prev_node_key = self.visitor.node_sort_key(prev_node)
                if node_key < prev_node_key:
                    yield error(node, "I100", "Import order is wrong")
            prev_node = node