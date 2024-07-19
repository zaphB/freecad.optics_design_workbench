# Optics Design Workbench

This workbench was inspired by the [OpticsWorkbench](https://github.com/chbergmann/OpticsWorkbench) and aims to extend its functionality towards design and optimization of optical assemblies.


## Installation

To make the Optics Design Workbench available in FreeCAD, install it using FreeCAD's built in add-on manager.

To be able to use the workbench as a regular python module run

```bash
pip3 install freecad.optics_design_workbench
```


## Manual/Offline installation without add-on manager

Head to the releases section and download the zipped source or your version of choice. Extract this zip to the Mod folder of your FreeCAD installation. The folder structure should be such that folder containing the `init_gui.py` is the third order subfolder below the Mod directory:

```bash
..../Mod/freecad.optics_design_workbench-1.2.3/freecad/optics_design_workbench/init_gui.py
```


## Development installation


`import freecad.something` causes a Segfault in many python interpreters, the workbench installs both the `freecad.optics_design_workbench` module and an identical `freecad_.optics_design_workbench` module. The latter can always be safely imported to use the parts of the module that are not related to FreeCAD.

To make the workbench available in FreeCAD use the workbench 


## Troubleshooting

When things don't work as expected first make sure you are actually running want you intend to run and whether the same version installed on the python and the FreeCAD side. To check this, run

```python
import freecad.optics_design_workbench
freecad.optics_design_workbench.versionInfo()
```

in the FreeCAD python shell and

```python
import freecad_.optics_design_workbench
freecad_.optics_design_workbench.versionInfo()
```

in your regular python shell of choice.

If any of the displayed versions and paths do not look as you would expected, first find out what's going wrong there. Due to the different discovery methods of a regular python shell and FreeCAD's python shell, it can easily happen that the two find completely different, possibly outdated, installations of the workbench.


## How to get started in FreeCAD

Select the Optics Design Workbench, place light sources, turn your existing objects into mirrors, lenses, absorbers and detectors and run Monte-Carlo simulations.

The workbench is still in an early stage, examples will appear here as soon as standard workflows for simulations and data analysis are implemented. The current idea is to have FreeCAD and a jupyter notebook open side-by-side. Simulations are configured and run in FreeCAD; the data analysis is done in the jupyter notebook.


## How to get started in python

After installation via pip import the module using

```python
import freecad_.optics_design_workbench
```

and try to find your way along usings python's help(...) and dir(...). The underscore in `freecad_` is important only as long as freecad segfaults when being imported from a regular python shell. If you can `import freecad` without a segfault on your system feel free to skip the underscore. 

The workbench is still in an early stage, examples will appear here as soon as standard workflows for simulations and data analysis are implemented. The current idea is to have FreeCAD and a jupyter notebook open side-by-side. Simulations are configured and run in FreeCAD; the data analysis is done in the jupyter notebook.
