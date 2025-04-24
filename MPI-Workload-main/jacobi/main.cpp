#include <stdio.h>
#include <stdlib.h>
#include <math.h>
#include <mpi.h>
#include <vector>  // Include vector header
#include <fstream>  // For file I/O
#include "main.h"
#include <random>
#define TOLERANCE 1e-6
using namespace std;


void jacobi_richardson(std::vector<double>& A, std::vector<double>& b, std::vector<double>& x, int local_rows, int rank, int N, int MAX_ITER ,int checkpoint_interval,string checkpoint_file,int iter,int num_procs, double& global_error) {
    int i, j;
    std::vector<double> D_inv(N);  // Inverse of diagonal
    std::vector<double> delta_x(N);
    std::vector<double> Ax(N);
    double local_error;
    double start = MPI_Wtime();
    // Extract diagonal and compute its inverse
    if (rank == 0) {
        for (i = 0; i < N; i++) {
            D_inv[i] = 1.0 / A[i * N + i];
        }
    }
    MPI_Bcast(D_inv.data(), N, MPI_DOUBLE, 0, MPI_COMM_WORLD);

    std::vector<int> recv_counts(num_procs);
    std::vector<int> displs(num_procs);
    int offset = 0;
    for (int i = 0; i < num_procs; i++) {
        recv_counts[i] = N / num_procs + (i < N % num_procs ? 1 : 0);
        displs[i] = offset;
        offset += recv_counts[i];
    }

    do {
        // Calculate Ax
        for (i = rank * local_rows; i < (rank + 1) * local_rows && i < N; i++) {
            Ax[i] = 0.0;
            for (j = 0; j < N; j++) {
                Ax[i] += A[i * N + j] * x[j];
            }
        }

        // Calculate delta_x = D^(-1)(b - Ax)
        for (i = rank * local_rows; i < (rank + 1) * local_rows && i < N; i++) {
            delta_x[i] = D_inv[i] * (b[i] - Ax[i]);
        }

        // Share delta_x with all processes
        MPI_Allgatherv(delta_x.data() + rank * local_rows, local_rows, MPI_DOUBLE,
               delta_x.data(), recv_counts.data(), displs.data(), MPI_DOUBLE, MPI_COMM_WORLD);

        // Calculate new x and error
        local_error = 0.0;
        for (i = rank * local_rows; i < (rank + 1) * local_rows && i < N; i++) {
            double relative_error = fabs(delta_x[i] / x[i]);
            local_error = fmax(local_error, relative_error);
            x[i] += delta_x[i];
        }

        // Find global maximum error
        MPI_Allreduce(&local_error, &global_error, 1, MPI_DOUBLE, MPI_MAX, MPI_COMM_WORLD);
        iter++;

        if (checkpoint_interval!=0  && iter % checkpoint_interval == 0) {

            std::vector<double> full_x(N);  // Holds the full x at rank 0
            MPI_Gatherv(x.data() + rank * local_rows, local_rows, MPI_DOUBLE,
                        full_x.data(), recv_counts.data(), displs.data(), MPI_DOUBLE, 0, MPI_COMM_WORLD);

            if(rank==0){
                printf("Iteration %d, Error: %e\n", iter, global_error);
                save_checkpoint(checkpoint_file, A, b, full_x, iter, global_error);
            }
        }

    } while ( iter < MAX_ITER);

    double end = MPI_Wtime();
    if (rank == 0) {
        cout << "Finished  " << MAX_ITER << " iterations. Time per iteration: " 
             << (end - start) / MAX_ITER << " seconds." << endl;
    }
}

int main(int argc, char* argv[]) {
    MPI_Init(&argc, &argv);

    int rank, num_procs;
    MPI_Comm_rank(MPI_COMM_WORLD, &rank);
    MPI_Comm_size(MPI_COMM_WORLD, &num_procs);

    int matrix_size = 1000;
    double tolerance = 1e-6;
    int max_iterations = 1000;
    int checkpoint_interval = 10;
    std::string results_folder = "./results/";
    std::string checkpoint_file = results_folder + "checkpoint.dat";
    bool restore = false;

    // Parse command-line arguments using CLI11
    CLI::App app{"Elastic Conjugate Gradient Solver"};
    app.add_option("-s,--matrix-size", matrix_size, "Matrix size (n)");
    app.add_flag("-r,--restore", restore, "Restore state from checkpoint");
    app.add_option("-c,--checkpoint-interval", checkpoint_interval, "Checkpoint interval");
    app.add_option("-f,--results-folder", results_folder, "Results folder");
    app.add_option("-i,--iterations", max_iterations, "Maximum iterations");
    CLI11_PARSE(app, argc, argv);

    // Allocate memory for matrix A, vector b, and x using std::vector
    std::vector<double> A(matrix_size * matrix_size);  // Matrix A
    std::vector<double> b(matrix_size);  // Vector b
    std::vector<double> x(matrix_size);  // Vector x (initialized to 0)
 
    int iter = 0;
    // Initialize A, b, and x

    if (!restore || !restore_checkpoint(checkpoint_file, A, b, x, iter,tolerance)) {
        random_device rd;
        mt19937 gen(rd());
        uniform_real_distribution<double> dist(-1*matrix_size, matrix_size);

        for (int i = 0; i < matrix_size; i++) {
            b[i] = dist(gen);
            x[i] = dist(gen);

            for (int j = 0; j < matrix_size; j++) {
                A[i * matrix_size + j] = dist(gen);
            }
            A[i * matrix_size + i] += matrix_size * 10;  // Ensure diagonal dominance
        }
    }

  
    double global_error = 0.0;
    int local_rows = matrix_size / num_procs + (rank < matrix_size % num_procs ? 1 : 0);

    // Call the Jacobi Richardson solver
    jacobi_richardson(A, b, x, local_rows, rank, matrix_size, max_iterations,checkpoint_interval,checkpoint_file,iter,num_procs, global_error);

    MPI_Finalize();
    return 0;
}