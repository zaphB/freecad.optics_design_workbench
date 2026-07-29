
.. _gettingStarted:
Getting Started
===============

Depending on the application one may want to use the optics design workbench interactively in the FreeCAD GUI or from a scripting environment such as jupyter notebooks. The following to guides 

.. toctree::
  :caption: Using the workbench through the FreeCAD GUI
  :maxdepth: 2

  getting-started-freecad

.. toctree::
  :caption: Using the workbench through jupyter notebooks
  :maxdepth: 2

  getting-started-jupyter

.. toctree::
  :caption: Getting to know all workbench features
  :maxdepth: 2

  getting-started-all-components


Advanced Examples
=================

After reading through the :ref:`gettingStarted` section and familiarizing yourself with the workbench, the following advanced examples aim to sketch real world simulation tasks.

.. toctree::
  :maxdepth: 1

  example-collimate-pointsource
  example-lambertiansource
  example-aspheric-lens
  example-spectrometer

API Reference
=============

.. autosummary::
  :toctree: api
  :recursive:

  optics_design_workbench.jupyter_utils
  optics_design_workbench.freecad_elements
  optics_design_workbench.simulation
