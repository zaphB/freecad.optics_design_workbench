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
sys.path.insert(0, os.path.abspath('../freecad'))

extensions = [
    'sphinx.ext.autodoc',
    'sphinx.ext.autosummary',
    'sphinx.ext.viewcode',
    'sphinx.ext.intersphinx',
    'numpydoc',
]

numpydoc_show_class_members = False  # verhindert doppelte Attribut-Listen
autosummary_generate = True

templates_path = ['_templates']
exclude_patterns = ['_build', 'Thumbs.db', '.DS_Store']

# -- Options for HTML output -------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#options-for-html-output

html_theme = 'pydata_sphinx_theme'
html_theme_options = {
  'github_url': 'https://github.com/zaphB/optics_design_workbench',
  'show_prev_next': False,
  'navigation_with_keys': True,
}
html_static_path = ['_static']
