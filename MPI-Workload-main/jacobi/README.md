# Jacobi Simulation Using C++

The Jacobi Richardson algorithm is an iterative method used to solve systems of linear equations. It is particularly useful for large-scale problems and can be parallelized using MPI.

## Algorithm Overview

The algorithm iteratively updates the solution vector `x` for the system of equations `Ax = b` using the following steps:

1. **Initialization**: Compute the inverse of the diagonal elements of matrix `A`.
2. **Iteration**:
   - Compute the product `Ax` for the local rows.
   - Calculate the difference `b - Ax`.
   - Update the solution vector `x` using the inverse of the diagonal elements.
   - Share the updated values among all processes.
   - Calculate the local and global errors.
3. **Checkpointing**: Periodically save the current state of the solution.

## Parallelization

The algorithm is parallelized using MPI:
- **MPI_Bcast**: Broadcast the inverse of the diagonal elements.
- **MPI_Allgatherv**: Share updated values of `x` among processes.
- **MPI_Allreduce**: Compute the global error.

## Checkpointing

The algorithm supports checkpointing to save the computation state periodically. This includes the matrix `A`, vector `b`, solution vector `x`, current iteration number, and global error.

# Steps to run : 

## Installation 
```sh
sudo apt install cmake libopenmpi-dev openmpi-bin
```
## How to Build

```sh
cmake CMakeLists.txt

make
```
## RUN
```sh
./elastic_jacobi [OPTIONS]

Options:
  -h,--help                   Print this help message and exit
  -s,--matrix-size INT        Total Bodies
  -r,--restore                Restore
  -c,--checkpoint-interval INT
                              Checkpoint interval
  -f,--results-folder TEXT    Results Folder
  -i,--iterations INT         Total number of iterations
```

```sh
mpirun -n 1 ./elastic_jacobi -s 1000 -i 5 -c 2
```

Run with c = 0 ,if you want to disable checkpointing.