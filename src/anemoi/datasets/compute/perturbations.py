# (C) Copyright 2024 ECMWF.
#
# This software is licensed under the terms of the Apache Licence Version 2.0
# which can be obtained at http://www.apache.org/licenses/LICENSE-2.0.
# In applying this licence, ECMWF does not waive the privileges and immunities
# granted to it by virtue of its status as an intergovernmental organisation
# nor does it submit to any jurisdiction.
#

import logging

import numpy as np
from climetlab.core.temporary import temp_file
from climetlab.readers.grib.output import new_grib_output

from anemoi.datasets.create.functions import assert_is_fieldset

LOG = logging.getLogger(__name__)

CLIP_VARIABLES = (
    "q",
    "cp",
    "lsp",
    "tp",
    "sf",
    "swl4",
    "swl3",
    "swl2",
    "swl1",
)

SKIP = ("class", "stream", "type", "number", "expver", "_leg_number", "anoffset")


def check_compatible(f1, f2, center_field_as_mars, ensemble_field_as_mars):
    assert f1.mars_grid == f2.mars_grid, (f1.mars_grid, f2.mars_grid)
    assert f1.mars_area == f2.mars_area, (f1.mars_area, f2.mars_area)
    assert f1.shape == f2.shape, (f1.shape, f2.shape)

    # Not in *_as_mars
    assert f1.metadata("valid_datetime") == f2.metadata("valid_datetime"), (
        f1.metadata("valid_datetime"),
        f2.metadata("valid_datetime"),
    )

    for k in set(center_field_as_mars.keys()) | set(ensemble_field_as_mars.keys()):
        if k in SKIP:
            continue
        assert center_field_as_mars[k] == ensemble_field_as_mars[k], (
            k,
            center_field_as_mars[k],
            ensemble_field_as_mars[k],
        )


def perturbations(
    *,
    members,
    center,
    clip_variables=CLIP_VARIABLES,
    output=None,
):

    keys = ["param", "level", "valid_datetime", "date", "time", "step", "number"]

    number_list = members.unique_values("number")["number"]
    n_numbers = len(number_list)

    assert None not in number_list

    LOG.info("Ordering fields")
    members = members.order_by(*keys)
    center = center.order_by(*keys)
    LOG.info("Done")

    if len(center) * n_numbers != len(members):
        LOG.error("%s %s %s", len(center), n_numbers, len(members))
        for f in members:
            LOG.error("Member: %r", f)
        for f in center:
            LOG.error("Center: %r", f)
        raise ValueError(f"Inconsistent number of fields: {len(center)} * {n_numbers} != {len(members)}")

    if output is None:
        # prepare output tmp file so we can read it back
        tmp = temp_file()
        path = tmp.path
    else:
        tmp = None
        path = output

    out = new_grib_output(path)

    seen = set()

    for i, center_field in enumerate(center):
        param = center_field.metadata("param")
        center_field_as_mars = center_field.as_mars()

        # load the center field
        center_np = center_field.to_numpy()

        # load the ensemble fields and compute the mean
        members_np = np.zeros((n_numbers, *center_np.shape))

        for j in range(n_numbers):
            ensemble_field = members[i * n_numbers + j]
            ensemble_field_as_mars = ensemble_field.as_mars()
            check_compatible(center_field, ensemble_field, center_field_as_mars, ensemble_field_as_mars)
            members_np[j] = ensemble_field.to_numpy()

            ensemble_field_as_mars = tuple(sorted(ensemble_field_as_mars.items()))
            assert ensemble_field_as_mars not in seen, ensemble_field_as_mars
            seen.add(ensemble_field_as_mars)

        # cmin=np.amin(center_np)
        # emin=np.amin(members_np)

        # if cmin < 0 and emin >= 0:
        #     LOG.warning(f"Negative values in {param} cmin={cmin} emin={emin}")
        #     LOG.warning(f"Center: {center_field_as_mars}")

        mean_np = members_np.mean(axis=0)

        for j in range(n_numbers):
            template = members[i * n_numbers + j]
            e = members_np[j]
            m = mean_np
            c = center_np

            assert e.shape == c.shape == m.shape, (e.shape, c.shape, m.shape)

            x = c - m + e

            if param in clip_variables:
                # LOG.warning(f"Clipping {param} to be positive")
                x = np.maximum(x, 0)

            assert x.shape == e.shape, (x.shape, e.shape)

            out.write(x, template=template)
            template = None

    assert len(seen) == len(members), (len(seen), len(members))

    out.close()

    if output is not None:
        return path

    from climetlab import load_source

    ds = load_source("file", path)
    assert_is_fieldset(ds)
    # save a reference to the tmp file so it is deleted
    # only when the dataset is not used anymore
    ds._tmp = tmp

    assert len(ds) == len(members), (len(ds), len(members))

    return ds
