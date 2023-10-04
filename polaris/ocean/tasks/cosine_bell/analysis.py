import warnings

import matplotlib.pyplot as plt
import numpy as np
import xarray as xr

from polaris import Step
from polaris.ocean.resolution import resolution_to_subdir


class Analysis(Step):
    """
    A step for analyzing the output from the cosine bell test case

    Attributes
    ----------
    resolutions : list of float
        The resolutions of the meshes that have been run

    icosahedral : bool
        Whether to use icosahedral, as opposed to less regular, JIGSAW
        meshes

    dependencies_dict : dict of dict of polaris.Steps
        The dependencies of this step
    """
    def __init__(self, component, resolutions, icosahedral, subdir,
                 dependencies):
        """
        Create the step

        Parameters
        ----------
        component : polaris.Component
            The component the step belongs to

        resolutions : list of float
            The resolutions of the meshes that have been run

        icosahedral : bool
            Whether to use icosahedral, as opposed to less regular, JIGSAW
            meshes

        subdir : str
            The subdirectory that the step resides in

        dependencies : dict of dict of polaris.Steps
            The dependencies of this step
        """
        super().__init__(component=component, name='analysis', subdir=subdir)
        self.resolutions = resolutions
        self.icosahedral = icosahedral
        self.dependencies_dict = dependencies

        self.add_output_file('convergence.png')

    def setup(self):
        """
        Add input files based on resolutions, which may have been changed by
        user config options
        """
        dependencies = self.dependencies_dict

        for resolution in self.resolutions:
            mesh_name = resolution_to_subdir(resolution)
            base_mesh = dependencies['mesh'][resolution]
            init = dependencies['init'][resolution]
            forward = dependencies['forward'][resolution]
            self.add_input_file(
                filename=f'{mesh_name}_mesh.nc',
                work_dir_target=f'{base_mesh.path}/base_mesh.nc')
            self.add_input_file(
                filename=f'{mesh_name}_init.nc',
                work_dir_target=f'{init.path}/initial_state.nc')
            self.add_input_file(
                filename=f'{mesh_name}_output.nc',
                work_dir_target=f'{forward.path}/output.nc')

    def run(self):
        """
        Run this step of the test case
        """
        plt.switch_backend('Agg')
        resolutions = self.resolutions
        xdata = list()
        ydata = list()
        for resolution in resolutions:
            mesh_name = resolution_to_subdir(resolution)
            rmseValue, nCells = self.rmse(mesh_name)
            xdata.append(nCells)
            ydata.append(rmseValue)
        xdata = np.asarray(xdata)
        ydata = np.asarray(ydata)

        p = np.polyfit(np.log10(xdata), np.log10(ydata), 1)
        conv = abs(p[0]) * 2.0

        yfit = xdata ** p[0] * 10 ** p[1]

        plt.loglog(xdata, yfit, 'k')
        plt.loglog(xdata, ydata, 'or')
        plt.annotate(f'Order of Convergence = {np.round(conv, 3)}',
                     xycoords='axes fraction', xy=(0.3, 0.95), fontsize=14)
        plt.xlabel('Number of Grid Cells', fontsize=14)
        plt.ylabel('L2 Norm', fontsize=14)
        plt.savefig('convergence.png', bbox_inches='tight', pad_inches=0.1)

        section = self.config['cosine_bell']
        if self.icosahedral:
            conv_thresh = section.getfloat('icos_conv_thresh')
            conv_max = section.getfloat('icos_conv_max')
        else:
            conv_thresh = section.getfloat('qu_conv_thresh')
            conv_max = section.getfloat('qu_conv_max')

        if conv < conv_thresh:
            raise ValueError(f'order of convergence '
                             f' {conv} < min tolerence {conv_thresh}')

        if conv > conv_max:
            warnings.warn(f'order of convergence '
                          f'{conv} > max tolerence {conv_max}')

    def rmse(self, mesh_name):
        """
        Compute the RMSE for a given resolution

        Parameters
        ----------
        mesh_name : str
            The name of the mesh

        Returns
        -------
        rmseValue : float
            The root-mean-squared error

        nCells : int
            The number of cells in the mesh
        """

        config = self.config
        latCent = config.getfloat('cosine_bell', 'lat_center')
        lonCent = config.getfloat('cosine_bell', 'lon_center')
        radius = config.getfloat('cosine_bell', 'radius')
        psi0 = config.getfloat('cosine_bell', 'psi0')
        convergence_eval_time = config.getfloat('spherical_convergence',
                                                'convergence_eval_time')

        ds_mesh = xr.open_dataset(f'{mesh_name}_mesh.nc')
        ds_init = xr.open_dataset(f'{mesh_name}_init.nc')
        # find time since the beginning of run
        ds = xr.open_dataset(f'{mesh_name}_output.nc')
        for j in range(len(ds.xtime)):
            tt = str(ds.xtime[j].values)
            tt.rfind('_')
            DY = float(tt[10:12]) - 1
            if DY == convergence_eval_time:
                sliceTime = j
                break
        HR = float(tt[13:15])
        MN = float(tt[16:18])
        t = 86400.0 * DY + HR * 3600. + MN
        # find new location of blob center
        # center is based on equatorial velocity
        R = ds_mesh.sphere_radius
        distTrav = 2.0 * 3.14159265 * R / (86400.0 * convergence_eval_time) * t
        # distance in radians is
        distRad = distTrav / R
        newLon = lonCent + distRad
        if newLon > 2.0 * np.pi:
            newLon -= 2.0 * np.pi

        # construct analytic tracer
        tracer = np.zeros_like(ds_init.tracer1[0, :, 0].values)
        latC = ds_mesh.latCell.values
        lonC = ds_mesh.lonCell.values
        temp = R * np.arccos(np.sin(latCent) * np.sin(latC) +
                             np.cos(latCent) * np.cos(latC) * np.cos(
            lonC - newLon))
        mask = temp < radius
        tracer[mask] = (psi0 / 2.0 *
                        (1.0 + np.cos(3.1415926 * temp[mask] / radius)))

        # oad forward mode data
        tracerF = ds.tracer1[sliceTime, :, 0].values
        rmseValue = np.sqrt(np.mean((tracerF - tracer)**2))

        return rmseValue, ds_init.dims['nCells']