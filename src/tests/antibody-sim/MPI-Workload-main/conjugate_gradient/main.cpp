#include <iostream>
#include <vector>
#include <cmath>
#include <mpi.h>
#include <string>
#include <fstream>
#include <algorithm>
#include "main.h"

using namespace std;

int main(int argc, char* argv[]) {
    MPI_Init(&argc, &argv);

    int rank, num_procs;
    MPI_Comm_rank(MPI_COMM_WORLD, &rank);
    MPI_Comm_size(MPI_COMM_WORLD, &num_procs);

    int matrix_size = 1000;
    double tolerance = 1e-6;
    int max_iterations = 1000;
    int checkpoint_interval = 10;
    string results_folder = "./results/";
    string checkpoint_file = results_folder + "checkpoint.dat";
    bool restore = false;

    // Parse command-line arguments
    CLI::App app{"Elastic Conjugate Gradient Solver"};
    app.add_option("-s,--matrix-size", matrix_size, "Matrix size (n)");
    app.add_flag("-r,--restore", restore, "Restore state from checkpoint");
    app.add_option("-c,--checkpoint-interval", checkpoint_interval, "Checkpoint interval");
    app.add_option("-f,--results-folder", results_folder, "Results folder");
    app.add_option("-i,--iterations", max_iterations, "Maximum iterations");
    CLI11_PARSE(app, argc, argv);

    int local_rows = matrix_size / num_procs + (rank < matrix_size % num_procs ? 1 : 0);

    vector<double> A(local_rows * matrix_size, 0.0);
    vector<double> b(local_rows, 0.0);
    vector<double> x(local_rows, 0.0);

    int iteration = 0;
    double global_error = 0.0;
    if (restore) {
        if (!restore_state(A, b, x, local_rows, matrix_size, rank, num_procs, checkpoint_file, iteration, global_error)) {
            if (rank == 0) {
                cout << "Failed to restore state. Initializing system from scratch." << endl;
            }
            initialize_system(A, b, x, local_rows, matrix_size, rank, num_procs);
        }
    } else {
        initialize_system(A, b, x, local_rows, matrix_size, rank, num_procs);
    }

    conjugate_gradient(A, b, x, local_rows, matrix_size, tolerance, max_iterations, checkpoint_interval, checkpoint_file, rank, num_procs,iteration);

    MPI_Finalize();
    return 0;
}

void initialize_system(vector<double>& A, vector<double>& b, vector<double>& x, int local_rows, int n, int rank, int num_procs) {
    fill(x.begin(), x.end(), 0.0);
    fill(b.begin(), b.end(), 1.0);

    for (int i = 0; i < local_rows; ++i) {
        int global_row = rank * (n / num_procs) + min(rank, n % num_procs) + i;
        A[i * n + global_row] = 4.0;
        if (global_row > 0) A[i * n + global_row - 1] = -1.0;
        if (global_row < n - 1) A[i * n + global_row + 1] = -1.0;
    }
}

void conjugate_gradient(vector<double>& A, vector<double>& b, vector<double>& x, 
                       int local_rows, int n, double tolerance, int max_iterations, 
                       int checkpoint_interval, string checkpoint_file, 
                       int rank, int num_procs,int iteration) {
    vector<double> r(local_rows), p(local_rows), Ap(local_rows);
    double local_residual_norm, global_residual_norm;

    // Initialize r = b - Ax
    matrix_vector_multiply(A, x, Ap, local_rows, n, rank, num_procs);
    for (int i = 0; i < local_rows; ++i) {
        r[i] = b[i] - Ap[i];
        p[i] = r[i];
    }

    local_residual_norm = dot_product(r, r, 0, local_rows);
    MPI_Allreduce(&local_residual_norm, &global_residual_norm, 1, MPI_DOUBLE, 
                  MPI_SUM, MPI_COMM_WORLD);
    double initial_residual_norm = sqrt(global_residual_norm);

    int rows_per_proc = n / num_procs;
    int remainder = n % num_procs;
    int offset = 0;
    vector<int> recvcounts_A(num_procs), displs_A(num_procs);
    vector<int> recvcounts_b(num_procs), displs_b(num_procs);
    vector<int> recvcounts_x(num_procs), displs_x(num_procs);
    for (int i = 0; i < num_procs; ++i) {
        recvcounts_A[i] = (n / num_procs + (i < n % num_procs ? 1 : 0)) * n;
        recvcounts_b[i] = n / num_procs + (i < n % num_procs ? 1 : 0);
        recvcounts_x[i] = recvcounts_b[i];

        displs_A[i] = (i > 0 ? displs_A[i - 1] + recvcounts_A[i - 1] : 0);
        displs_b[i] = (i > 0 ? displs_b[i - 1] + recvcounts_b[i - 1] : 0);
        displs_x[i] = displs_b[i];
    }

    double start = MPI_Wtime();

    while (iteration < max_iterations) {
        matrix_vector_multiply(A, p, Ap, local_rows, n, rank, num_procs);

        double local_pAp = dot_product(p, Ap, 0, local_rows);
        double global_pAp;
        MPI_Allreduce(&local_pAp, &global_pAp, 1, MPI_DOUBLE, MPI_SUM, MPI_COMM_WORLD);

        global_pAp += 1e-12; // Avoid division by zero

        double alpha = global_residual_norm / (global_pAp); 

        // Update x and r
        for (int i = 0; i < local_rows; ++i) {
            x[i] += alpha * p[i];
            r[i] -= alpha * Ap[i];
        }

        double local_new_residual = dot_product(r, r, 0, local_rows);
        double new_global_residual;
        MPI_Allreduce(&local_new_residual, &new_global_residual, 1, MPI_DOUBLE, 
                      MPI_SUM, MPI_COMM_WORLD);

        global_residual_norm+=1e-12; // Avoid division by zero
        double beta = new_global_residual / (global_residual_norm);
        for (int i = 0; i < local_rows; ++i) {
            p[i] = r[i] + beta * p[i];
        }

        global_residual_norm = new_global_residual;

        if (checkpoint_interval!=0 && iteration % checkpoint_interval == 0) {
            try {
                if (rank == 0) {
                    vector<double> global_A(n * n, 0.0);
                    vector<double> global_b(n, 0.0);
                    vector<double> global_x(n, 0.0);

                    // Rank 0 gathers data from all processes
                    MPI_Gatherv(A.data(), local_rows * n, MPI_DOUBLE, 
                                global_A.data(), recvcounts_A.data(), displs_A.data(), 
                                MPI_DOUBLE, 0, MPI_COMM_WORLD);
                    
                    MPI_Gatherv(b.data(), local_rows, MPI_DOUBLE, 
                                global_b.data(), recvcounts_b.data(), displs_b.data(), 
                                MPI_DOUBLE, 0, MPI_COMM_WORLD);

                    MPI_Gatherv(x.data(), local_rows, MPI_DOUBLE, 
                                global_x.data(), recvcounts_x.data(), displs_x.data(), 
                                MPI_DOUBLE, 0, MPI_COMM_WORLD);

                    save_checkpoint(checkpoint_file, global_A, global_b, global_x, 
                                    iteration, sqrt(global_residual_norm));
                    cout << "Checkpoint saved at iteration " << iteration << ", residual norm: " 
                         << sqrt(global_residual_norm) << endl;
                } else {
                    // Other ranks send their data to rank 0
                    MPI_Gatherv(A.data(), local_rows * n, MPI_DOUBLE, 
                                nullptr, nullptr, nullptr, 
                                MPI_DOUBLE, 0, MPI_COMM_WORLD);
                    
                    MPI_Gatherv(b.data(), local_rows, MPI_DOUBLE, 
                                nullptr, nullptr, nullptr, 
                                MPI_DOUBLE, 0, MPI_COMM_WORLD);

                    MPI_Gatherv(x.data(), local_rows, MPI_DOUBLE, 
                                nullptr, nullptr, nullptr, 
                                MPI_DOUBLE, 0, MPI_COMM_WORLD);
                }
            } catch (const std::exception& e) {
                cerr << "Error during checkpoint: " << e.what() << endl;
                MPI_Abort(MPI_COMM_WORLD, 1);
            }
        }


        iteration++;
    }

    double end = MPI_Wtime();
    if (rank == 0) {
        cout << "Finished in " << iteration << " iterations. Time per iteration: " 
             << (end - start) / iteration << " seconds." << endl;
    }
}

double dot_product(const vector<double>& v1, const vector<double>& v2, int start, int end) {
    double sum = 0.0;
    for (int i = start; i < end; ++i) {
        sum += v1[i] * v2[i];
    }
    return sum;
}

void matrix_vector_multiply(const vector<double>& A, const vector<double>& vec, 
                          vector<double>& result, int local_rows, int n, 
                          int rank, int num_procs) {
    vector<int> sendcounts(num_procs);
    vector<int> displs(num_procs);
    int total_rows = 0;

    for (int p = 0; p < num_procs; ++p) {
        sendcounts[p] = (n / num_procs) + (p < n % num_procs ? 1 : 0);
        displs[p] = total_rows;
        total_rows += sendcounts[p];
    }

    // Gather the complete vec from all processes
    vector<double> global_vec(n);
    MPI_Allgatherv(vec.data(), local_rows, MPI_DOUBLE,
                   global_vec.data(), sendcounts.data(), displs.data(),
                   MPI_DOUBLE, MPI_COMM_WORLD);

    // Clear result
    result.assign(local_rows, 0.0);

    // Compute local portion of matrix-vector product
    for (int i = 0; i < local_rows; ++i) {
        for (int j = 0; j < n; ++j) {
            result[i] += A[i * n + j] * global_vec[j];
        }
    }
}

bool restore_state(vector<double>& A, vector<double>& b, vector<double>& x, 
                   int local_rows, int n, int rank, int num_procs, 
                   const string& checkpoint_file, int& iteration, 
                   double& global_error) {
    vector<double> global_A, global_b, global_x;

    if (rank == 0) {
        global_A.resize(n * n, 0.0);
        global_b.resize(n, 0.0);
        global_x.resize(n, 0.0);

        if (!restore_checkpoint(checkpoint_file, global_A, global_b, global_x, 
                                iteration, global_error)) {
            cerr << "Failed to restore checkpoint." << endl;
            return false;
        }
    }

    // Prepare counts and displacements for scattering
    vector<int> recvcounts_A(num_procs), displs_A(num_procs);
    vector<int> recvcounts_b(num_procs), displs_b(num_procs);
    vector<int> recvcounts_x(num_procs), displs_x(num_procs);

    int rows_per_proc = n / num_procs;
    int remainder = n % num_procs;
    int offset = 0;

    for (int i = 0; i < num_procs; ++i) {
        recvcounts_A[i] = (n / num_procs + (i < n % num_procs ? 1 : 0)) * n;
        recvcounts_b[i] = n / num_procs + (i < n % num_procs ? 1 : 0);
        recvcounts_x[i] = recvcounts_b[i];

        displs_A[i] = (i > 0 ? displs_A[i - 1] + recvcounts_A[i - 1] : 0);
        displs_b[i] = (i > 0 ? displs_b[i - 1] + recvcounts_b[i - 1] : 0);
        displs_x[i] = displs_b[i];
    }

    // Scatter data from rank 0 to all processes
    MPI_Scatterv(global_A.data(), recvcounts_A.data(), displs_A.data(), MPI_DOUBLE, 
                 A.data(), local_rows * n, MPI_DOUBLE, 0, MPI_COMM_WORLD);
    MPI_Scatterv(global_b.data(), recvcounts_b.data(), displs_b.data(), MPI_DOUBLE, 
                 b.data(), local_rows, MPI_DOUBLE, 0, MPI_COMM_WORLD);
    MPI_Scatterv(global_x.data(), recvcounts_x.data(), displs_x.data(), MPI_DOUBLE, 
                 x.data(), local_rows, MPI_DOUBLE, 0, MPI_COMM_WORLD);

    return true;
}


