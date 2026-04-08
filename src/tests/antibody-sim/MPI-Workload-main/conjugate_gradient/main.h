#ifndef MAIN_H
#define MAIN_H

#include <string>
#include <CLI11.hpp>

using namespace std;

void initialize_system(vector<double>& A, vector<double>& b, vector<double>& x, int local_rows, int n, int rank, int num_procs);
void conjugate_gradient(vector<double>& A, vector<double>& b, vector<double>& x, int local_rows, int n, double tolerance, int max_iterations, int checkpoint_interval, string checkpoint_file, int rank, int num_procs,int iteration);
double dot_product(const vector<double>& v1, const vector<double>& v2, int start, int end);
void matrix_vector_multiply(const vector<double>& A, const vector<double>& vec, vector<double>& result, int local_rows, int n, int rank, int num_procs);
void save_checkpoint(const string& filename, const vector<double>& A, const vector<double>& b, const vector<double>& x, 
                     int iter, double global_error);
bool restore_checkpoint(const string& filename, vector<double>& A, vector<double>& b, vector<double>& x, 
                        int& iter, double& global_error);
bool restore_state(vector<double>& A, vector<double>& b, vector<double>& x, 
                   int local_rows, int n, int rank, int num_procs, 
                   const string& checkpoint_file, int& iteration, 
                   double& global_error);

#endif