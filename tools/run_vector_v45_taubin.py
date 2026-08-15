#!/usr/bin/env python3
import build_vector_v45_taubin as b

# Keep the proven v4.4 shoreline exactly unchanged. The Taubin experiment targets
# the residual scalloping of the internal bathymetric contours only.
b.TARGET_ITERATIONS[0] = 0
b.main()
