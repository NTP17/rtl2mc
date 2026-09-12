"""Cross-platform entry point: python rtl2mc.py run -f design.f."""
from rtl2mc.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
