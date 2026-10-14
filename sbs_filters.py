"""Independent CPU filters. Spatial kernels/strength and HSL response are approximations."""
import numpy as np

APPROXIMATE={'blur','dirmotionblur','warp','directionalwarp','normal','hsl'}
PARAMETERS={
 'blur':{'intensity','pixelsize','tiling'},'dirmotionblur':{'intensity','mblurangle','tiling'},
 'warp':{'intensity','tiling'},'directionalwarp':{'intensity','warpangle','tiling'},
 'normal':{'intensity','inversedy','input2alpha','tiling'},
 'hsl':{'hue','saturation','luminosity'},
 'shuffle':{'channelred','channelgreen','channelblue','channelalpha'}}

def apply(op,param,source,u,v,sample):
    a=source('input1');size=a.shape[0]
    mode=int(param('tiling',3))
    if mode not in range(4):raise ValueError('不支持的平铺模式')
    def at(image,x,y):return sample(image,x,y,mode)
    def gradient(image):
        dx=(at(image,u+1/size,v)[...,0]-at(image,u-1/size,v)[...,0])*.5
        dy=(at(image,u,v+1/size)[...,0]-at(image,u,v-1/size)[...,0])*.5
        return dx,dy
    if op=='shuffle':
        channels=[int(param(key,i)) for i,key in enumerate(('channelred','channelgreen','channelblue','channelalpha'))]
        if any(c not in range(8) for c in channels):raise ValueError('Shuffle 目前支持输入一/二的 RGBA 共 8 个通道')
        b=source('input2') if any(c>=4 for c in channels) else a
        return np.stack([(a if c<4 else b)[...,c%4] for c in channels],axis=-1)
    if op=='hsl':
        hue,saturation,lightness=[float(param(k,.5)) for k in ('hue','saturation','luminosity')]
        if any(not 0<=x<=1 for x in (hue,saturation,lightness)):raise ValueError('HSL 参数范围为 0–1')
        rgb=np.clip(a[...,:3],0,1);hi=rgb.max(-1);lo=rgb.min(-1);delta=hi-lo;L=(hi+lo)*.5
        safe=np.where(delta==0,1,delta)
        H=np.where(hi==rgb[...,0],(rgb[...,1]-rgb[...,2])/safe,np.where(hi==rgb[...,1],2+(rgb[...,2]-rgb[...,0])/safe,4+(rgb[...,0]-rgb[...,1])/safe))/6
        H=(H+hue-.5)%1
        denom=1-np.abs(2*L-1);S=np.divide(delta,denom,out=np.zeros_like(delta),where=denom>1e-8)
        def adjust(x,t):return x*(2*t) if t<=.5 else x+(1-x)*(2*t-1)
        S=adjust(S,saturation);L=adjust(L,lightness)
        C=(1-np.abs(2*L-1))*S;X=C*(1-np.abs((H*6)%2-1));zero=np.zeros_like(C);sector=np.floor(H*6).astype(int)%6
        colors=np.stack([np.stack(t,-1) for t in ((C,X,zero),(X,C,zero),(zero,C,X),(zero,X,C),(X,zero,C),(C,zero,X))])
        result=a.copy();result[...,:3]=np.take_along_axis(colors,sector[None,...,None],axis=0)[0]+(L-C*.5)[...,None];return result
    strength=float(param('intensity',1))
    if not np.isfinite(strength):raise ValueError('强度必须为有限数')
    if op=='normal':
        dx,dy=gradient(a);scale=strength*size/256
        xyz=np.stack((-dx*scale,dy*scale*(-1 if param('inversedy',0) else 1),np.ones_like(dx)),axis=-1)
        xyz/=np.linalg.norm(xyz,axis=-1,keepdims=True)
        return np.concatenate((xyz*.5+.5,a[...,:1] if param('input2alpha',1) else np.ones_like(a[...,:1])),axis=-1)
    if op in ('warp','directionalwarp'):
        if strength==0:return a.copy()
        field=source('inputgradient' if op=='warp' else 'inputintensity')
        if op=='warp':dx,dy=gradient(field);dx*=strength/256;dy*=strength/256
        else:
            angle=float(param('warpangle',0))*2*np.pi;dx=field[...,0]*strength/256*np.cos(angle);dy=field[...,0]*strength/256*np.sin(angle)
        return at(a,u+dx,v+dy)
    if strength<0:raise ValueError('模糊强度不能为负')
    if strength==0:return a.copy()
    if op=='dirmotionblur':
        radius=strength*size/256
        if radius>64:raise ValueError('CPU 定向模糊预览半径超过 64 像素')
        count=max(3,2*int(np.ceil(radius))+1);angle=float(param('mblurangle',0))*2*np.pi
        result=np.zeros_like(a)
        for t in np.linspace(-radius,radius,count):result+=at(a,u+t/size*np.cos(angle),v+t/size*np.sin(angle))/count
        return result
    pixel=np.asarray(param('pixelsize',[1,1]),np.float32)
    if pixel.shape!=(2,) or np.any(pixel<=0):raise ValueError('Blur pixelsize 需要两个正数')
    sigmas=strength*size/256*pixel
    if np.any(sigmas>32):raise ValueError('CPU 高斯模糊预览 sigma 超过 32 像素')
    result=a.copy()
    for axis,sigma in enumerate(sigmas):
        radius=max(1,int(np.ceil(3*sigma)));offsets=np.arange(-radius,radius+1);weights=np.exp(-.5*(offsets/max(sigma,1e-8))**2);weights/=weights.sum()
        blurred=np.zeros_like(result)
        for off,weight in zip(offsets,weights):blurred+=at(result,u+(off/size if axis==0 else 0),v+(off/size if axis==1 else 0))*weight
        result=blurred
    return result
