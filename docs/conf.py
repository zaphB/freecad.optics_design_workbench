# Configuration file for the Sphinx documentation builder.
#
# For the full list of built-in configuration values, see the documentation:
# https://www.sphinx-doc.org/en/master/usage/configuration.html

# -- Project information -----------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#project-information

project = 'optics_design_workbench'
copyright = '2026, Philipp Bredol'
author = 'Philipp Bredol'

# -- General configuration ---------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#general-configuration

# setup numpydoc
import os
import sys
print('='*50)
_path = os.path.abspath('../freecad/')
if not os.path.exists(_path):
  raise ValueError(f'path to module {_path} not found')
sys.path.insert(0, _path)
sys.path.append('.')
import optics_design_workbench
print(optics_design_workbench.__file__)
print('='*50)

extensions = [
  'sphinx.ext.autodoc',
  'sphinx.ext.autosummary',
  'sphinx.ext.viewcode',
  'sphinx.ext.intersphinx',
  'numpydoc',
  'nbsphinx',
  'notebook_directive', # <- custom directive to embed notebooks
]

numpydoc_show_class_members = False # switch off numpy-docs methods generator (is handled by custom _template instead)
autosummary_generate = True

templates_path = ['_templates']
exclude_patterns = ['_build', 'Thumbs.db', '.DS_Store']

# -- Options for HTML output -------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#options-for-html-output

html_theme = 'pydata_sphinx_theme'
html_theme_options = {
  'github_url': 'https://github.com/zaphB/freecad.optics_design_workbench',
  'show_prev_next': True,
  'navigation_with_keys': True,
  'show_nav_level': 1, # sidebar default opened depth
  'navigation_depth': 4, # sidebar depth
  'logo': {
      'text': 'Optics Design Workbench',
      'image_light': '_static/icons/workbench.svg',
      'image_dark': '_static/icons/workbench.svg', 
  },
}
html_static_path = ['_static']
html_css_files = ['tweaks.css']
html_title = 'FreeCAD Optics Design Workbench Docs'

# insert this at begin of every doc page
rst_prolog = '''
.. warning::
   This documentation is still a work in progress. Missing an example, tutorial, or API reference you need? Getting confused by an ambiguous explanation? Open an issue and let me know what you'd like to see:
   https://github.com/zaphB/freecad.optics_design_workbench/issues

'''

# insert this at end of every doc page
rst_epilog = '''

:sub:`~happy ray tracing!`

'''
