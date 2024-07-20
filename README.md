# Optics Design Workbench

This workbench was inspired by the [OpticsWorkbench](https://github.com/chbergmann/OpticsWorkbench) and aims to extend its functionality towards design and optimization of optical assemblies.

Feel free to ask any question in the [forum thread](https://forum.freecad.org/viewtopic.php?t=89264).


## Prerequisites

FreeCAD version >=0.21, python packages numpy, scipy, matplotlib, atomicwrites. A jupyter notebook installation is recommended.


## Installation

To make the Optics Design Workbench available in FreeCAD, install it using FreeCAD's built in add-on manager.

To be able to use the workbench as a regular python module run

```bash
pip3 install freecad.optics_design_workbench
```


## Manual/offline installation without add-on manager

Head to the releases section and download the zipped source of your version of choice. Extract this zip to the Mod folder of your FreeCAD installation. The folder structure should be such that folder containing the `init_gui.py` is the third order subfolder below the Mod directory:

```bash
..../Mod/freecad.optics_design_workbench-1.2.3/freecad/optics_design_workbench/init_gui.py
```


## Development installation

Clone this repository, install the python module in development mode using `pip install -e .`. Create a symlink in your FreeCAD's Mod folder pointing to the directory if the cloned directory. With this setup, changes in the cloned repository folder will be effective immediately when restarting FreeCAD. Avoid using regular PyPi or add-on manager installations in parallel with the development installation.


## Examples

To get started, FCStd files and corresponding jupyter notebooks can be found the examples folder of this repository.


### Gaussian beam point source and detector

[examples/1-source-and-detector](./examples/1-source-and-detector)

#### Ray-fan simulation mode

The ray-fan mode renders rays for cross-sections of the solid angle with a spacing matching the inverse power density of the light source. This mode renders fast and gives a good first impression where the optical power of your sources ends up.

![ray-fan mode screenshot](./examples/1-source-and-detector/screenshot-ray-fan.png)


#### Monte-Carlo simulation mode

In the Monte-Carlo simulation mode, rays are placed randomly in the full solid angle according to the given power density of the light source. If the simulation is run in continuous mode, recorded ray hits will be stored to disk and can be loaded and further analyzed with the accompanying notebook in the example folder.

![monte-carlo mode screenshot](./examples/1-source-and-detector/screenshot-monte-carlo.png)


## Spherical lens and parabolic mirror

[examples/2-lens-and-mirror](./examples/2-lens-and-mirror)

Any geometric body in FreeCAD can become member of one of the `OpticalGroup`s to turn them into reflective, refractive, absorbing or ray-detecting objects. This example contains spherical lenses and slotted parabolic mirrors, transparent and absorbing detectors. When running the continuous simulation, folders for all objects that have set `Store Hits` to true will be generated.

![lens and mirror screenshot](./examples/2-lens-and-mirror/screenshot.png)



## Troubleshooting

When things don't work as expected first make sure you are actually running want you intend to run and whether the same workbench version is installed on the python and the FreeCAD side. To check this, run

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

Make sure that the workbench versions seen by FreeCAD and by python match and that all the displayed versions and paths match your expectations.


## How to get started in FreeCAD

Select the Optics Design Workbench, place light sources, turn your existing objects into mirrors, lenses, absorbers and detectors and run Monte-Carlo simulations.

The workbench is still in an early stage, examples will appear here as soon as standard workflows for simulations and data analysis are implemented. The current idea is to have FreeCAD and a jupyter notebook open side-by-side. Simulations are configured and run in FreeCAD; the data analysis is done in the jupyter notebook.


## How to get started in python

After installation via pip import the module using

```python
import freecad_.optics_design_workbench
```

So far the only documentation are a few docstrings here and there, which can be explored using python's help(...) and dir(...). The underscore in `freecad_` is important only as long as freecad segfaults when being imported from a regular python shell. If you can `import freecad` without a segfault on your system feel free to skip the underscore. 

The workbench is still in an early stage, examples will appear here as soon as standard workflows for simulations and data analysis are implemented. The current idea is to have FreeCAD and a jupyter notebook open side-by-side. Simulations are configured and run in FreeCAD; the data analysis is done in the jupyter notebook.
