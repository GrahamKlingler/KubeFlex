cmake_minimum_required(VERSION 3.10)
project(ElasticCG)

set(CMAKE_CXX_COMPILER mpic++)
set(CMAKE_CXX_FLAGS "${CMAKE_CXX_FLAGS} -O3 -g -std=c++11")

find_library(MPI Names mpi PATHS)
message(STATUS "MPI ${MPI}")
include_directories(../utils)

add_executable(elastic_cg main.cpp ../utils/utils.cpp)