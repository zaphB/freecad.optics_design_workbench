#!/usr/bin/env python
"""
Remove output, prompt numbers and other runtime data from jupyter
notebooks. If the metadata of a notebook contains
```
"git" : { "suppress_output" : false }
```
the notebooks are not changed by this script.

See also this blogpost: http://pascalbugnion.net/blog/ipython-notebooks-and-git.html.

Usage instructions for manual run
=================================

Execute
```
./clean-ipynb.py path/to/your/notebook.ipynb
```
to clean the specified notebook file in place. This script will
ask for confirmation to prevent unintended deletion of outputs.


Usage instructions as git filter
================================

1. Put this script in a directory that is on the system's path.
   For future reference, I will assume you saved it in
   `~/scripts/ipynb_drop_output`.
2. Make sure it is executable by typing the command
   `chmod +x ~/scripts/ipynb_drop_output`.
3. Register a filter for ipython notebooks by
   putting the following line in `~/.config/git/attributes`:
   `*.ipynb  filter=clean_ipynb`
4. Connect this script to the filter by running the following
   git commands:
   git config --global filter.clean_ipynb.clean ipynb_drop_output
   git config --global filter.clean_ipynb.smudge cat
You may need to "touch" the notebooks for git to actually register a change, if
your notebooks are already under version control.

Notes
=====

This script is inspired by http://stackoverflow.com/a/20844506/827862, but
lets the user specify whether the output of a notebook should be suppressed
in the notebook's metadata, only works for python 3 and allows to specify
a filename as argument, to clean a notebook file in place.
"""

import sys
import json

def main():
  # select stdin/stdout or file method
  if len(sys.argv) > 1:
    with open(sys.argv[1], 'r') as f:
      nb = f.read()
    useStdout = False
    print(f'are you sure that you want to clean all cell outputs '
          f'from {sys.argv[1]}? (y/N) ', end='')
    if input().lower() != 'y':
      print('canceled')
      return
  else:
    nb = sys.stdin.read()
    useStdout = True

  # store result in this variable
  result = None

  # parse json
  json_in = json.loads(nb)

  # set uncleaned notebook as result if suppress_outputs is
  # present in metadata and is false
  nb_metadata = json_in["metadata"]
  suppress_output = True
  if "git" in nb_metadata:
    if "suppress_outputs" in nb_metadata["git"] and not nb_metadata["git"]["suppress_outputs"]:
      suppress_output = False
  if not suppress_output:
    result = nb

  # clean only if result is not yet set
  if result is None:

    # function that removes all unneeded outputs from a
    # cell in place
    def strip_output_from_cell(cell, i):
      if "outputs" in cell:
        cell["outputs"] = []
      if "prompt_number" in cell:
        del cell["prompt_number"]
      if "execution_count" in cell:
        cell["execution_count"] = None
      if 'id' in cell:
        cell['id'] = f'{i:04d}'

    # apply function to every cell
    for i, cell in enumerate(json_in["cells"]):
      strip_output_from_cell(cell, i)

    # strip runtime data from metadata
    if 'metadata' in json_in:
      json_in['metadata'] = {}
      #m = json_in['metadata']
      #if 'kernelspec' in m:
      #  del m['kernelspec']
      #if 'language_info' in m:
      #  if 'version' in m['language_info']:
      #    del m['language_info']['version']

  # write results either to stdout or to the input file
  if useStdout:
    outStream = sys.stdout
  else:
    outStream = open(sys.argv[1], 'w')
  json.dump(json_in, outStream, sort_keys=True, indent=1, separators=(",",": "))
  if not useStdout:
    print('done')

if __name__ == '__main__':
  main()
