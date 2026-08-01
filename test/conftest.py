import nbconvert
import pytest
import os
import linecache

import matplotlib
import matplotlib.pyplot
# make sure matplotlib uses backend that does not open any windows
matplotlib.use("Agg")

@pytest.fixture(autouse=True)
def closeAllFigures():
  # reset rcParams to defaults before each test
  matplotlib.pyplot.rcdefaults()
  yield
  # close all plots after each test
  import matplotlib.pyplot as plt
  plt.close("all")

@pytest.fixture
def runNotebook(tmp_path, monkeypatch):
  def _runNotebook(filename):
    # generate python code and filter lines that may make trouble later
    filename = str(filename)
    if not filename.endswith('.ipynb'):
      filename += '.ipynb'
    source, _ = nbconvert.PythonExporter().from_filename(filename)
    filteredSource = '\n'.join([l for l in source.split('\n') 
                              if 'get_ipython' not in l
                                 and l.strip() ])
    _filename = f'<generated-from-{filename}>'
    sourceLines = filteredSource.splitlines(keepends=True)
    linecache.cache[_filename] = (len(filteredSource), None, sourceLines, _filename)
    code = compile(filteredSource, _filename, "exec")
    ns = {}
    monkeypatch.chdir(os.path.dirname(os.path.abspath(filename)))
    exec(code, locals=ns, globals=ns)

  yield _runNotebook
