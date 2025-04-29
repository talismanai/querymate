import os
import sys
sys.path.insert(0, os.path.abspath('../..'))

project = 'QueryMate'
copyright = '2024, Mauricio Banduk'
author = 'Mauricio Banduk'
release = '0.1.0'

extensions = [
    'sphinx.ext.autodoc',
    'sphinx.ext.napoleon',
    'sphinx.ext.viewcode',
    'sphinx.ext.intersphinx',
    'sphinx_rtd_theme',
]

templates_path = ['_templates']
exclude_patterns = []

html_theme = 'sphinx_rtd_theme'
html_static_path = ['_static']

intersphinx_mapping = {
    'python': ('https://docs.python.org/3', None),
    'sqlmodel': ('https://sqlmodel.tiangolo.com/', None),
    'fastapi': ('https://fastapi.tiangolo.com/', None),
} 