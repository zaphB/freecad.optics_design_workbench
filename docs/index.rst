
.. _gettingStarted:
Getting Started
===============

The Optics Design Workbench is (or intends to be) a physically accurate geometric forward ray-tracer with seamless FreeCAD and jupyter-lab integration. Ray tracing is a suitable approximation to calculate the propagation of waves whenever diffraction and interference effects are negligible. As the name implies the optics design workbench is mainly intended for optics design and uses the language of optics in all its components. However it is in principle applicable to any wave propagation problem when the ray tracing approximation is viable.

..
  --------------------------------------------------------------
  only change the following paragraph after making sure 
  the Optics Workbench author agrees

The `Optics Design Workbench`_ is inspired by the `Optics Workbench`_ but follows different goals. The Optics Workbench puts its focus on being self-explanatory to allow for a smooth learning-by-doing experience without the need to bother with external software like jupyter notebooks. The Optics Design Workbench includes more complex simulation and optimization schemes at the cost of having "a bit of a learning curve". So if you neither need light sources with freely configurable power density distribution, nor Monte-Carlo simulation nor a jupyter integration, the `Optics Workbench`_ is most likely the better choice.

.. _`Optics Workbench`: https://github.com/chbergmann/OpticsWorkbench
.. _`Optics Design Workbench`: .
..
  --------------------------------------------------------------


As mentioned, the workbench comes with *two* integrations, or two faces if you want: The workbench is a FreeCAD Addon, designed to be used in the FreeCAD GUI and integrate well with the CAD model development process. At the same time it is a python package optimized for usage in jupyter lab environments to enjoy the benefits of the entire scientific python ecosystem, e.g. data visualization, fit routines, optimizers, connectivity with other software, FEM solvers or your own python package. In this documentation the python package is usually mentioned in the context of jupyter notebooks, but in principle it can be installed in any other python environment which you have the power to install packages into. Depending on your application you will likely use either the FreeCAD GUI integration or the jupyter integration more intensely than the other, however you will likely have to gain a basic understanding of both integrations to complete any meaningful task.

The `first chapter`_ of this guide introduces how optical simulations are created in the FreeCAD GUI by setting up a basic example project step by step. The `second chapter`_ shows how the simulation results generated in the first chapter can be visualized using a jupyter notebook. The chapter goes on with more advanced jupyter notebooks examples that are e.g. capable of manipulating FCStd geometry, running geometry-parameter sweeps or letting an optimization algorithm find the best geometry for a given optimization target. The `third and final chapter`_ contains one simple example for all the components of the workbench.

.. _`basic examples`:
Learning with examples
----------------------

.. _`first chapter`:
.. toctree::
  :maxdepth: 2

  getting-started-freecad

.. _`second chapter`:
.. toctree::
  :maxdepth: 2

  getting-started-jupyter

.. _`third and final chapter`:
.. toctree::
  :maxdepth: 2

  getting-started-all-components

..
  Advanced Examples
  -----------------
  .
  After working through the `basic examples`_ and familiarizing yourself with the workbench, the following advanced examples aim to sketch real world simulation tasks:
  .
  .. toctree::
    :maxdepth: 1
  .
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
  optics_design_workbench.distributions
  optics_design_workbench.freecad_elements
  optics_design_workbench.simulation
  optics_design_workbench.gui_windows


Manual installation methods
===========================

Install a specific workbench version
------------------------------------

To install a specific version of the workbench python package in just tell pip so: `pip install optics_design_workbench==v1.2.3` will install workbench version v1.2.3.

.. __`https://github.com/zaphB/freecad.optics_design_workbench/releases`

To install the FreeCAD addon in a specific version requires a few more steps, because the Addon manager will generally install the latest version of the workbench. To manually install a specific workbench version, head to the `releases section`__ of the workbench repository and download the zipped source of your version of choice. Extract downloaded zip archive to the Mod folder of your FreeCAD installation. Make sure that the folder containing the `init_gui.py` is on the third subfolder level below the Mod directory, e.g. like this:

```bash
..../Mod/freecad.optics_design_workbench-1.2.3/freecad/optics_design_workbench/init_gui.py
```

Note that changes in the workbench source only become effective after restarting FreeCAD. 


Development installation
------------------------

It is not straightforward to install python packages in FreeCADs internal python shell. The easiest way to make sure the workbench python dependencies are installed is to install the workbench using the Addon manager first.

Avoid using regular PyPi or Addon manager installations in parallel with the development installation. Therefore use the Addon Manager to uninstall the workbench again and use `pip uninstall optics_design_workbench` to uninstall any PyPi installation.

.. __`https://github.com/zaphB/freecad.optics_design_workbench`

Then install the python package in development mode, clone the `github repository`__ and install the python module in editable mode using `pip install -e .`. Create a symlink in your FreeCAD's Mod folder pointing to the directory of the cloned repository (If the workbench is not appearing make sure that the folder containing the `init_gui.py` is on the third subfolder level below the Mod directory). With this setup, changes in the cloned repository folder will be effective immediately when restarting FreeCAD as described above.

Note that changes in the workbench source only become effective after restarting FreeCAD or the respective jupyter kernel.
