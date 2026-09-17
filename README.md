![Tests](./badge-tests.svg) ![Coverage](./badge-coverage.svg) 


# Optics Design Workbench

This workbench was inspired by the [OpticsWorkbench](https://github.com/chbergmann/OpticsWorkbench) and aims to extend its functionality towards design and optimization of optical assemblies.

The [documentation](https://optics-design-workbench.readthedocs.io) is far from complete but growing.

Feel free to ask any question in the [forum thread](https://forum.freecad.org/viewtopic.php?t=89264).


## Troubleshooting

When encountering errors please make sure that the workbench is up-to-date (Addon Manager->Optics Design Workbench->Update).
To make sure you are actually running what you intend to run and that the same workbench version is installed on the python and the FreeCAD side, run

```python
import freecad.optics_design_workbench
freecad.optics_design_workbench.versionInfo()
```

in the FreeCAD python shell and

```python
import optics_design_workbench
optics_design_workbench.versionInfo()
```

in your regular python shell of choice.

Make sure that the workbench versions seen by FreeCAD and by python match and that all the displayed versions and paths match your expectations.
