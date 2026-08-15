#!/usr/bin/env python3
import build_vector_v45_taubin as b

# Keep the proven v4.4 shoreline and tiny deep zones exactly unchanged.
# Taubin targets only the interior contours where the raster-frequency scallop
# is visually relevant.
b.TARGET_ITERATIONS[0] = 0
b.TARGET_ITERATIONS[6] = 0
b.TARGET_ITERATIONS[7] = 0
b.main()
