'''
Thanks ChatGPT!
'''

from pathlib import Path

from docutils import nodes
from docutils.parsers.rst import Directive, directives


def parseCellSelection(selection, cellCount):
  """Parse a cell selection such as '0,2,5-7' into a list of indices."""
  indices = set()
  for part in selection.split(","):
    part = part.strip()
    if not part:
      continue
    if "-" in part:
      start, end = part.split("-", 1)
      if start.strip():
        start = int(start.strip())
      else:
        start = 0
      if end.strip():
        end = int(end.strip())
      else:
        end = cellCount-1
      if start > end:
        raise ValueError(f"invalid cell range: {part}")
      indices.update(range(start, end+1))
    else:
      indices.add(int(part))
  invalid = [i for i in indices if i < 0 or i >= cellCount]
  if invalid:
    raise ValueError(f'cell index out of range: {invalid}; '
                     f'notebook contains {cellCount} cells' )
  return sorted(indices)


class NotebookDirective(Directive):
  required_arguments = 1
  optional_arguments = 0
  has_content = False
  option_spec = {
    'cells': directives.unchanged,    
    'class': directives.class_option,
  }

  def run(self):
    from nbconvert import HTMLExporter
    import nbformat

    # parse path and append suffix if not present
    notebookPath = Path(self.arguments[0])
    if not str(notebookPath).endswith('.ipynb'):
      notebookPath = Path(str(notebookPath)+'.ipynb')

    # resolve path relative to the current .rst source file.
    current_source = Path(self.state.document.current_source)
    notebookPath = (current_source.parent / notebookPath).resolve()
    if not notebookPath.exists():
      error = self.state_machine.reporter.error(
        f"notebook not found: {notebookPath}", line=self.lineno, )
      return [error]

    # try to run nbformat
    try:
      notebook = nbformat.read(notebookPath, as_version=4)
    except Exception as exc:
      error = self.state_machine.reporter.error(
        f"failed to read {notebookPath}: {exc}", line=self.lineno )
      return [error]

    # optionally select specific cells
    if "cells" in self.options:
      try:
        selectedIndices = parseCellSelection(self.options["cells"],
                                               len(notebook.cells) )
      except (ValueError, TypeError) as exc:
        error = self.state_machine.reporter.error(
          f"invalid cell selection in {notebookPath}: {exc}", line=self.lineno)
        return [error]
      notebook.cells = [ notebook.cells[i] for i in selectedIndices ]

    # run html export and return results
    exporter = HTMLExporter()
    try:
      body, resources = exporter.from_notebook_node(notebook)
    except Exception as exc:
      error = self.state_machine.reporter.error(
        f"Could not convert notebook {notebookPath}: {exc}",
        line=self.lineno )
      return [error]
    classes = ["inline-notebook"]
    if "class" in self.options:
      classes.extend(self.options["class"])
    html = ( f'<div class="{" ".join(classes)}">\n'
             f"{body}\n"
             f"</div>" )
    return [nodes.raw("", html, format="html")]

def setup(app):
  app.add_directive("notebook", NotebookDirective)
  return {"version": "1.0", "parallel_read_safe": True}
