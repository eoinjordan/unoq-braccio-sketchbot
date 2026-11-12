# Licences in this repository

Three licences apply. Which one covers a file depends on the folder it is in.

| Folder | Licence | Text |
| --- | --- | --- |
| Everything not listed below | MIT | [LICENSE](LICENSE) |
| `hardware/pencil-grip/` | CC BY-SA 4.0 | [hardware/pencil-grip/LICENSE](hardware/pencil-grip/LICENSE) |
| `hardware/braccio-arm/` | GPL-3.0 | [hardware/braccio-arm/LICENSE](hardware/braccio-arm/LICENSE) |
| `site/hardware/pencil-grip/` | CC BY-SA 4.0 | byte-for-byte copies of `hardware/pencil-grip/`, published by GitHub Pages |
| `site/hardware/braccio-arm/` | GPL-3.0 | byte-for-byte copies of `hardware/braccio-arm/`, published by GitHub Pages |

## hardware/pencil-grip (CC BY-SA 4.0)

The printable Sketchbot parts and their OpenSCAD sources: pencil grips, pen
fingers, camera mounts, the XIAO round display holder, the Braccio finger
reference mesh and the preview pictures. By *eoinedge*, published as
[Thingiverse thing:7382987](https://www.thingiverse.com/thing:7382987).

## hardware/braccio-arm (GPL-3.0)

Seven STL meshes of the Braccio arm, copied unmodified from
<https://github.com/lots-of-things/braccio_moveit_gazebo>
(article: <https://opus.stedden.org/2020/08/braccio-moveit-gazebo/>). They are
simulation visual meshes in millimetres.

The folder also holds `xiao_round_display_on_wrist.scad` and the two pictures
rendered from it. They show the round display holder on those meshes, so they
are kept with them under GPL-3.0.

Nothing outside that folder and its site copy includes the meshes.
`scripts/check_xiao_holder.py` and `sim/render_arm.py` read them at run time;
what they write goes to `output/`, which is not committed.

## Bundled web assets

Licences of the libraries bundled into the Studio and the setup site are in
`web/static/dist/licenses/` and `site/assets/licenses/`.
