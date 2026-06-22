import multiprocessing

from materia_epd.cli import main

if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()
