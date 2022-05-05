Python API documenattion generation
===================================

This theme includes an optional extension that generates Python API
documentation pages.

- A separate page is generated for each documented entity.

- Top-level module-level entities are organized into *groups*, specified by the
  ``:group:`` field within the docstring.  The :rst:dir:`python-apigen` directive
  is used to insert a *summary* of a group into an existing page.

- The summary of a group shows an abbreviated signature and an abbreviated
  description for each entity in the group; the name portion of the signature is
  a link to the separate page for that entity.

- Class members are also organized into groups, also using the ``:group:`` field
  within their docstrings.  Class members without a group are assigned to a
  default group based on their name.  The summaries for each class member group
  are included on the page that documents the class.

- There is special support for pybind11-defined overloaded functions.  Each
  overload is documented as a separate function; each overload is identified by
  the ``:overload:`` field specified within its docstring.

Usage
-----

To use this extension, add :python:`"sphinx_immaterial.python_apigen"` it to the
list of extensions in :file:`conf.py` and define the
:confval:`python_apigen_modules` configuration option.

For example:

.. code-block:: python

    extensions = [
        # other extensions...
        "sphinx_immaterial.python_apigen",
    ]

    python_apigen_modules = {
          "my_module": "api",
    }


Configuration
-------------

.. confval:: python_apigen_modules

   Maps module names to the output directory relative to the source directory.

   All entities defined by the specified modules are documented.

   For example, with the following added to :file:`conf.py`:

   .. code-block:: python

      python_apigen_modules = {
          "my_module": "my_api",
          "my_other_module": "other_api",
      }

   The following generated documents will be used:

   ====================== ==================
   Python object          Generated document
   ====================== ==================
   my_module.Foo          my_api/Foo
   my_module.Foo.method   my_api/Foo.method
   my_module.Bar          my_api/Bar
   my_other_module.Baz    other_api/Baz
   ====================== ==================

Subscript methods
^^^^^^^^^^^^^^^^^

*Subscript methods* are attributes defined on an object that support subscript
syntax.  For example:

.. code-block:: python

   arr.vindex[1, 2:5, [1, 2, 3]]

These subscript methods can be implemented as follows:

.. code-block:: python

   class MyArray:
       class _Vindex:
           def __init__(self, arr: MyArray):
               self.arr = arr

           def __getitem__(self, sel: Selection):
               # Do something with `self.arr` and `sel`.
               return result

       @property
       def vindex(self) -> MyArray._Vindex:
           return MyArray._Vindex(self)

Based on the :confval:`python_apigen_subscript_method_types` option, this
extension can recognize this pattern and display :python:`vindex` as:

.. code-block::

   vindex[sel: Selection]

rather than as a normal property.

.. confval:: python_apigen_subscript_method_types

   Regular expression pattern that matches the return type annotations of
   properties that define subscript methods.

   Return type annotations can be specified either as real annotations or in the
   textual signature specified as the first line of the docstring.

   The default value matches any name beginning with an underscore,
   e.g. :python:`_Vindex` in the example above.
