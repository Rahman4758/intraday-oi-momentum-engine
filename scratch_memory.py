import tracemalloc
from services.instrument_mapper import InstrumentMapper

def main():
    tracemalloc.start()
    mapper = InstrumentMapper()
    mapper.load_instruments()
    current, peak = tracemalloc.get_traced_memory()
    print(f"Current memory usage is {current / 10**6}MB; Peak was {peak / 10**6}MB")
    tracemalloc.stop()

if __name__ == '__main__':
    main()
