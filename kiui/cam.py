import numpy as np
from .op import *
from scipy.spatial.transform import Rotation

# camera convention:
# world coordinate is right-hand, +x = right, +y = up, +z = forward
# camera coordinate is the same (forward is target --> campos).
# elevation in (-90, 90), from +y (-90) --> -y (+90)
# azimuth in (-180, 180), from +z (0/-360) --> +x (90/-270) --> -z (180/-180) --> -x (270/-90) --> +z (360/0)

''' common world coordinate system conventions

   OpenGL          OpenCV           Blender        Unity             
Right-handed       Colmap                        Left-handed  

     +y                +z           +z  +y         +y  +z                                               
     |                /             |  /           |  /                                               
     |               /              | /            | /                                                   
     |______+x      /______+x       |/_____+x      |/_____+x                                          
    /               |                                                                                        
   /                |                                                                                                  
  /                 |                                                                                         
 +z                 +y                                                                                           

'''

''' camera pose matrix
[[Forward_x, Up_x, Right_x, Position_x],
 [Forward_y, Up_y, Right_y, Position_y],
 [Forward_z, Up_z, Right_z, Position_z],
 [0,         0,    0,       1         ]]
The xyz follows corresponding world coordinate system.
'''


# look at rotation matrix
def look_at(campos, target, opengl=True):
    # campos: [N, 3], camera/eye position
    # target: [N, 3], object to look at
    # return: [N, 3, 3], rotation matrix
    if not opengl:
        # camera forward aligns with -z
        forward_vector = safe_normalize(target - campos)
        up_vector = np.array([0, 1, 0], dtype=np.float32)
        right_vector = safe_normalize(np.cross(forward_vector, up_vector))
        up_vector = safe_normalize(np.cross(right_vector, forward_vector))
    else:
        # camera forward aligns with +z
        forward_vector = safe_normalize(campos - target)
        up_vector = np.array([0, 1, 0], dtype=np.float32)
        right_vector = safe_normalize(np.cross(up_vector, forward_vector))
        up_vector = safe_normalize(np.cross(forward_vector, right_vector))
    R = np.stack([right_vector, up_vector, forward_vector], axis=1)
    return R


# elevation & azimuth to pose (cam2world) matrix
def orbit_camera(elevation, azimuth, radius=1, is_degree=True, target=None, opengl=True):
    # radius: scalar
    # elevation: scalar, in (-90, 90), from +y to -y is (-90, 90)
    # azimuth: scalar, in (-180, 180), from +z to +x is (0, 90)
    # return: [4, 4], camera pose matrix
    if is_degree:
        elevation = np.deg2rad(elevation)
        azimuth = np.deg2rad(azimuth)
    x = radius * np.cos(elevation) * np.sin(azimuth)
    y = - radius * np.sin(elevation)
    z = radius * np.cos(elevation) * np.cos(azimuth)
    if target is None:
        target = np.zeros([3], dtype=np.float32)
    campos = np.array([x, y, z]) + target  # [3]
    T = np.eye(4, dtype=np.float32)
    T[:3, :3] = look_at(campos, target, opengl)
    T[:3, 3] = campos
    return T

# orbit pose to elevation & azimuth
def undo_orbit_camera(T, is_degree=True):
    # T: [4, 4], camera pose matrix
    # return: elevation, azimuth, radius
    campos = T[:3, 3]
    radius = np.linalg.norm(campos)
    elevation = np.arcsin(-campos[1] / radius)
    azimuth = np.arctan2(campos[0], campos[2])
    if is_degree:
        elevation = np.rad2deg(elevation)
        azimuth = np.rad2deg(azimuth)
    return elevation, azimuth, radius

# perspective matrix
def get_perspective(fovy, aspect=1, near=0.01, far=1000):
    # fovy: field of view in degree.
    
    y = np.tan(np.deg2rad(fovy) / 2)
    return np.array(
        [
            [1 / (y * aspect), 0, 0, 0],
            [0, -1 / y, 0, 0],
            [
                0,
                0,
                -(far + near) / (far - near),
                -(2 * far * near) / (far - near),
            ],
            [0, 0, -1, 0],
        ],
        dtype=np.float32,
    )

class OrbitCamera:
    def __init__(self, W, H, r=2, fovy=60, near=0.01, far=100):
        self.W = W
        self.H = H
        self.radius = r  # camera distance from center
        self.fovy = np.deg2rad(fovy)  # deg 2 rad
        self.near = near
        self.far = far
        self.center = np.array([0, 0, 0], dtype=np.float32)  # look at this point
        self.rot = Rotation.from_matrix(np.eye(3))
        self.up = np.array([0, 1, 0], dtype=np.float32)  # need to be normalized!

    @property
    def fovx(self):
        return 2 * np.arctan(np.tan(self.fovy / 2) * self.W / self.H)

    @property
    def campos(self):
        return self.pose[:3, 3]

    # pose (c2w)
    @property
    def pose(self):
        # first move camera to radius
        res = np.eye(4, dtype=np.float32)
        res[2, 3] = self.radius  # opengl convention...
        # rotate
        rot = np.eye(4, dtype=np.float32)
        rot[:3, :3] = self.rot.as_matrix()
        res = rot @ res
        # translate
        res[:3, 3] -= self.center
        return res

    # view (w2c)
    @property
    def view(self):
        return np.linalg.inv(self.pose)

    # projection (perspective)
    @property
    def perspective(self):
        y = np.tan(self.fovy / 2)
        aspect = self.W / self.H
        return np.array(
            [
                [1 / (y * aspect), 0, 0, 0],
                [0, -1 / y, 0, 0],
                [
                    0,
                    0,
                    -(self.far + self.near) / (self.far - self.near),
                    -(2 * self.far * self.near) / (self.far - self.near),
                ],
                [0, 0, -1, 0],
            ],
            dtype=np.float32,
        )

    # intrinsics
    @property
    def intrinsics(self):
        focal = self.H / (2 * np.tan(self.fovy / 2))
        return np.array([focal, focal, self.W // 2, self.H // 2], dtype=np.float32)

    # model-view-perspective
    @property
    def mvp(self):
        return self.perspective @ np.linalg.inv(self.pose)  # [4, 4]

    def orbit(self, dx, dy):
        # rotate along camera up/side axis!
        side = self.rot.as_matrix()[:3, 0]
        rotvec_x = self.up * np.radians(-0.05 * dx)
        rotvec_y = side * np.radians(-0.05 * dy)
        self.rot = Rotation.from_rotvec(rotvec_x) * Rotation.from_rotvec(rotvec_y) * self.rot

    def scale(self, delta):
        self.radius *= 1.1 ** (-delta)

    def pan(self, dx, dy, dz=0):
        # pan in camera coordinate system (careful on the sensitivity!)
        self.center += 0.0005 * self.rot.as_matrix()[:3, :3] @ np.array([dx, -dy, dz])

    def from_angle(self, elevation, azimuth, is_degree=True):
        if is_degree:
            elevation = np.deg2rad(elevation)
            azimuth = np.deg2rad(azimuth)
        x = self.radius * np.cos(elevation) * np.sin(azimuth)
        y = - self.radius * np.sin(elevation)
        z = self.radius * np.cos(elevation) * np.cos(azimuth)
        campos = np.array([x, y, z])  # [N, 3]
        rot_mat = look_at(campos, np.zeros([3], dtype=np.float32))
        self.rot = Rotation.from_matrix(rot_mat)