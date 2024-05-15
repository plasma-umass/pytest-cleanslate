import pytest
import sys
from . import plugin

if __name__ == "__main__":
    sys.exit(pytest.main(sys.argv[1:], plugins=[plugin.CleanSlatePlugin()]))
