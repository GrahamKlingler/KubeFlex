# Conjugate Gradient Simulation Using C++

The Conjugate Gradient (CG) method is an iterative algorithm for solving large systems of linear equations, specifically those of the form \(Ax = b\), where \(A\) is a symmetric positive-definite matrix. It is particularly useful for sparse systems. The method combines the principles of gradient descent and conjugate directions to efficiently converge to the solution.

## Steps:

1. **Initialization**:
   - Start with an initial guess \(x_0\) and compute the initial residual \(r_0 = b - Ax_0\).
   - Set the initial direction \(p_0 = r_0\).

2. **Iteration**:
   - Compute the step size \(\alpha_k = \frac{r_k^T r_k}{p_k^T A p_k}\).
   - Update the solution \(x_{k+1} = x_k + \alpha_k p_k\).
   - Update the residual \(r_{k+1} = r_k - \alpha_k A p_k\).
   - Compute the new direction coefficient \(\beta_k = \frac{r_{k+1}^T r_{k+1}}{r_k^T r_k}\).
   - Update the direction \(p_{k+1} = r_{k+1} + \beta_k p_k\).

3. **Convergence**:
   - Repeat the iteration until the residual \(r_k\) is sufficiently small.

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
./elastic_cg [OPTIONS]

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
mpirun -n 1 ./elastic_cg -s 1000 -i 5 -c 2
```

Run with c = 0 ,if you want to disable checkpointing.