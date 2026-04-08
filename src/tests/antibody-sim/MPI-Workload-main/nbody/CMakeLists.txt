cmake_minimum_required(VERSION 3.10)
project(ElasticNbody)

set(CMAKE_CXX_COMPILER mpic++)
set(CMAKE_CXX_FLAGS "${CMAKE_CXX_FLAGS} -O3 -g -std=c++11")

find_library(MPI Names mpi PATHS)
message(STATUS "MPI ${MPI}")
include_directories(../utils)

add_executable(elastic_nbody CLI11.hpp utils.cpp main.cpp)

# Standalone build (no MPI) for CRIU migration testing
add_executable(elastic_nbody_nompi CLI11.hpp main_nompi.cpp)
set_target_properties(elastic_nbody_nompi PROPERTIES
    CXX_STANDARD 11
    COMPILE_FLAGS "-O3 -g"
)
target_compile_options(elastic_nbody_nompi PRIVATE -std=c++11)