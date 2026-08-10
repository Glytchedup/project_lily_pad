# Silhouette credits

These outlines come from [PhyloPic](https://www.phylopic.org/), a database of
life-form silhouettes built for phylogenetic diagrams. They are the only part of
Lily Pad not drawn by its own code — everything painted **on** them (colour,
shading, patterns, eyes, outline, motion) is still procedural.

Every file here is under a **public-domain dedication**, chosen deliberately:
PhyloPic also hosts CC-BY-NC-SA images, and the default image a taxon shows on
the site is often one of those. NonCommercial has no place in this repo — it
would follow anyone who forked it. If you add a silhouette, check the licence on
the specific image, not the taxon.

Attribution is not required for any of these. It is given anyway, because
several are by working palaeoartists.

| File | Taxon | Artist | Licence | PhyloPic image |
|---|---|---|---|---|
| `giraffe.svg` | *Giraffa* | An Ignorant Atheist | CC0 1.0 | `bbce74cf-4df3-4b7d-8b1d-f5b24dd3264a` |
| `triceratops.svg` | *Triceratops* | Richard Rich | CC0 1.0 | `57d2507a-be74-453b-8522-f6993b2fc401` |
| `whale.svg` | *Megaptera* | (unattributed) | CC0 1.0 | `fd8d3e5e-24a0-4aa2-9211-987ff86007dd` |

Look one up at `https://www.phylopic.org/images/<image id>`.

The files are unmodified potrace output as served by the PhyloPic API. They are
solid black shapes with a real alpha channel, which is exactly what
`effects/animal_stencil.py` needs: it paints through that alpha rather than
recolouring pixels, so the outline stays crisp at any size.
