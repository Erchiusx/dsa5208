CXX ?= g++
MPICXX ?= mpic++
GPU_CXX ?= nvc++
CXXFLAGS ?= -O2 -std=c++17 -Wall -Wextra -Wpedantic
GPU_FLAGS ?= -O2 -std=c++17 -mp=gpu
INCLUDES = -Ithird_party/chess-library
SOURCE = src/main.cpp
GCC_STDLIB_DIR = $(dir $(shell $(CXX) -print-file-name=libstdc++.so.6))
GCC_OPENMP_DIR = $(dir $(shell $(CXX) -print-file-name=libgomp.so.1))

.PHONY: all cpu mpi gpu test clean
all: cpu

build:
	mkdir -p build

cpu: build
	$(CXX) $(CXXFLAGS) -fopenmp $(INCLUDES) $(SOURCE) -o build/chess_search

mpi: build
	$(MPICXX) $(CXXFLAGS) -fopenmp -DUSE_MPI $(INCLUDES) $(SOURCE) \
		-Wl,-rpath,$(GCC_STDLIB_DIR) -Wl,-rpath,$(GCC_OPENMP_DIR) \
		-o build/chess_search_mpi

gpu: build
	$(GPU_CXX) $(GPU_FLAGS) $(INCLUDES) $(SOURCE) -o build/chess_search_gpu

test: cpu
	bash tests/smoke.sh build/chess_search

clean:
	rm -f build/chess_search build/chess_search_mpi build/chess_search_gpu
