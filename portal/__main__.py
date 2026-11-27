from gartner.config import ROOT
import sys

# ensure project root on path when running as script
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from portal.app import main

if __name__ == "__main__":
    main()
