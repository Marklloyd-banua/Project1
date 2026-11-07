# Third-party software and asset inventory

This inventory records package license metadata present in the installed dependency package manifests. It is not a full legal review, a project source-code license, or confirmation that a marketplace listing meets its current rules. Keep notices required by the selected license with any distribution.

## Direct runtime dependencies

| Package | Version in current lockfile | Package license metadata |
| --- | --- | --- |
| React / React DOM | 19.3.1 | MIT |
| React Router DOM | 7.18.5 | MIT |
| Bootstrap | 5.3.8 | MIT |
| Bootstrap Icons | 1.13.2 | MIT |
| Recharts | 3.10.1 | MIT |
| Redux Toolkit | 2.14.0 | MIT (declared, currently not imported by application source) |

## Fonts and local assets

`src/index.css` loads DM Sans and Manrope from Google Fonts at runtime. This repository does not include the font files or a font-specific notice. Verify the applicable font license and attribution requirements before self-hosting or redistributing those files.

The repository also contains `src/assets/hero.png`, `src/assets/react.svg`, `src/assets/vite.svg`, `public/favicon.svg`, and `public/icons.svg`. Their provenance and redistribution terms are not documented here; verify ownership or licensing before including them in a commercial archive.

## Limitations

The table covers direct runtime packages only. It does not enumerate transitive dependencies or development tools. Review the lockfile and package license files when preparing a redistribution. The project owner must separately choose and include a license for this template's original source code.
