# Nbody Simulation Using C++

The problem tries to find how n-bodies (particles) move under the effect of each others gravitational forces. This notes are based on [link](https://medium.com/swlh/create-your-own-n-body-simulation-with-python-f417234885e9).

Each particle $i \in N$ is defined by:
* Mass $m_i$
* Position $p_i = [x_i, y_i, z_i]$
* Velocity $v_i = [v_{x_i},v_{y_i},v_{z_i}]$

## Location Particles
To compute the new position of each particle we need the acceleration that can be done using `Newton Law of universal gravitation`.

$$ a_i = G \sum_{j\neq i} m_j \frac{r_j - r_i}{|r_j-r_i|^3}$$

where $G = 6.67 \times 10^{-11} \ \ m^3/kg/s^2$

## Computing New Velocities and locations
The new location and velocities are calculated with a lep-from scheme called (`kick-drift-kick`). In the 1st kick step the velocity are updated every ${\Delta t}/2$:

$$v_i = v_i + \frac{\Delta t}{2} \times a_i$$

Followed by a full-step drift:
$$r_i = r_i + \Delta t \times v_i$$

Finally the velocity is updated again (kick) but with the new acceleration:

$$v_i = v_i + \frac{\Delta t}{2} \times a_i$$

## Energy Validation
Since we are using approximations we need to validate the total energy of the system.

$$E_{Tot} = \sum_i \frac{1}{2}m_iv_i^2 - \sum_{1\leq i <j\leq N}\frac{Gm_im_j}{|r_j-r_j|}$$.
The first part is KE and the second part is PE.

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
./elastic_nbody [OPTIONS]

Options:
  -h,--help                   Print this help message and exit
  -b,--total-bodies INT       Total Bodies
  -r,--restore                Restore
  -p,--print                  Print initial and final values
  -c,--checkpoint-interval INT
                              Checkpoint interval
  -f,--results-folder TEXT    Results Folder
  -i,--iterations INT         Total number of iterations
```

```sh
mpirun -n 1 ./elastic_nbody -b 1000 -i 5 -c 2
```
The results include the `checkpoint.dat` and `checkpoint_time` and `iteration_time`. The current code don't include power measurements. You can use RAPL or measure utilization for this.