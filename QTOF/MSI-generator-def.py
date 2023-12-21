#====================================================================
# EXTERNAL RAW-MSI-generator SETUP
#====================================================================

#====================================================================
# Library import
#====================================================================
import os
import sys
import time
import math
from tqdm.notebook import tqdm

import numpy as np
import pandas as pd

import matplotlib.pyplot as plt

# MS API
try:
    # thermo
    from pymsfilereader import MSFileReader
    # QTOF
    from multiplierz.mzAPI import mzFile
except:
    pass
#====================================================================

#==================================        misc         ============================================
class HiddenPrints:
    def __enter__(self):
        self._original_stdout = sys.stdout
        sys.stdout = open(os.devnull, 'w')

    def __exit__(self, exc_type, exc_val, exc_tb):
        sys.stdout.close()
        sys.stdout = self._original_stdout

#==================================   data processing   ============================================
def Get_LineList(NameBody, NamePost):
    """
    Returns list of line numbers as strings in ascending order.
    The filenames must end with the line number immediately after NameBody and before NamePost
    """
    dirlist = os.listdir(os.path.split(NameBody)[0])
    for i, name in enumerate(os.listdir(os.path.split(NameBody)[0])):
        # removes all files that do not end with NamePost
        if not name.casefold().endswith(NamePost.casefold()):
            dirlist.remove(name)

    # Get Line List by keeping all numbers following NameBody
    LineList = []
    dirlist_nums = [int(i.replace(os.path.split(NameBody)[-1],'').replace(NamePost.lower(),'').replace(NamePost.upper(),'')) for i in dirlist]
    for i in range(2000):
        try:
            line = dirlist[dirlist_nums.index(i)]
            LineList.append(line.replace(os.path.split(NameBody)[-1],'').replace(NamePost.lower(),'').replace(NamePost.upper(),''))
        except:
            pass

    return LineList

def pixels_to_imgs(pixels, NumLine, NumSpePerLine):
    '''
    input pixels: (heigh_dim * lenth_dim, n_imgs) ~ (n_pixels, n_mzs)
    output imgs: (n_imgs, heigh_dim, lenth_dim)
    '''
    imgs = pixels.T.reshape(-1, NumLine, NumSpePerLine)
    return imgs

def imgs_to_pixels(imgs):
    '''
    input imgs: (n_imgs, heigh_dim, lenth_dim)
    output pixels: (heigh_dim * lenth_dim, n_imgs) ~ (n_pixels, n_mzs)
    '''
    pixels = imgs.reshape((imgs.shape[0], -1)).T
    return pixels

#==================================   raw file info extraction, no filters   ============================================
'''
Works for .raw and .d files.  -> specify the NamePost of raw files.
'''
#================   basics for .d files   ==================
def get_d_data_points(data, index):
    '''
    input: 
    data: the spectra object
    index: the index of scan
    
    output:
    mzs: np array of m/z
    Is: np array of intensities
    '''
    spectrum = np.array(data.scan(index, 'profile')) # 1. profile or centroid, default: profile 
    mzs = spectrum[:, 0]
    Is = spectrum[: ,1]
    return mzs, Is

def get_d_headers(data):
    '''
    input: 
    data: the spectra object
    
    output:
    Acq_times: np array of acquisition times
    TICs: np array of TICs
    '''
    headers = np.array(data.xic())
    Acq_times = np.round(headers[:,0], 4)
    TICs = headers[:,1]
    return Acq_times, TICs

#================   wrap up   ==================
def check_dim(LineList, NameBody, NamePost, ShowNumLineSpe=True):
    NumSpePerLine = np.empty([0,2],int)
    NameBody = NameBody
    NamePost = NamePost
    tot_acq_times = []

    for i, linnum in enumerate(LineList):
        file_dir = NameBody+str(linnum)+NamePost
        if NamePost == '.raw':
            data=MSFileReader(file_dir)
            NumSpectra=int(data.GetNumSpectra())
            data.Close()
        if NamePost == '.d':
            with HiddenPrints():
                data = mzFile(file_dir)
            Acq_times, TICs = get_d_headers(data)
            tot_acq_time = max(Acq_times)
            tot_acq_times.append(tot_acq_time)
            NumSpectra = TICs.shape[0]
            data.close()
        NumSpePerLine=np.append(NumSpePerLine,[[int(i),NumSpectra]],axis=0)

    ColName=np.array(['# of line','# of spectra'])
    NumSpePerLine=pd.DataFrame(NumSpePerLine, columns=ColName)
    NumSpePerLine=NumSpePerLine.set_index('# of line')
    
    # show results
    if ShowNumLineSpe:
        print(NumSpePerLine)
        print('\nline scan spectra summary\n# of lines is: {}\nmean # of spectra is: {}\nmin # of spectra is: {}'.format(
              NumSpePerLine.shape[0], int(round(NumSpePerLine.mean().item())), int(NumSpePerLine.min().item())))
    return NumSpePerLine, tot_acq_times

def get_pixels_values_nofilter(NameBody, NamePost, LineList, NumSpePerLine, TimeStamps_aligned, MassList, MassTolerance):
    # initiate accumulator
    pixels=np.empty([0,(MassList.shape[0]+1)])

    for i, linnum in enumerate(LineList):
        # 1D accumulator for TimeStamps
        NumSpePerLine_meta = NumSpePerLine['# of spectra'][i]
        TimeStamps = np.zeros((NumSpePerLine_meta))
    
        # 2D accumulator for 1 line, meta: current data, no meta: aligned data
        pixelsPerLine_meta = np.zeros((NumSpePerLine_meta, MassList.shape[0]+1))
        pixelsPerLine = np.zeros((TimeStamps_aligned.shape[0], MassList.shape[0]+1)) 
        
        # file name and timing
        StaTime=time.time()
        file_dir = NameBody + str(linnum) + NamePost
        
        if NamePost == '.raw':
            data = MSFileReader(file_dir)

            for j in tqdm(range(1,NumSpePerLine_meta+1)):     # grab header and spectrum at each scan
                # grab header
                header = data.GetScanHeaderInfoForScanNum(j)
                TimeStamp = header['StartTime']
                TIC = header["TIC"]
                pixelsPerLine_meta[j-1,0] = TIC
                TimeStamps[j-1] = TimeStamp
                
                # grab spectrum
                spectrum = data.GetMassListFromScanNum(j)
                mz = np.array(spectrum[0][0])
                IntensityPoints = np.array(spectrum[0][1])
                for k in range(MassList.shape[0]):
                    PeakPoints = IntensityPoints[(mz > MassList[k]*(1-MassTolerance*0.000001))&(mz < MassList[k]*(1+MassTolerance*0.000001))]
                    Intensity = PeakPoints.sum()
                    pixelsPerLine_meta[j-1,k+1] = Intensity
            data.Close()
        
        if NamePost == '.d':
            with HiddenPrints():
                data = mzFile(file_dir)
            # grab headers for all scans
            TimeStamps, TICs = get_d_headers(data)
            TimeStamps = TimeStamps[:NumSpePerLine_meta]
            TICs = TICs[:NumSpePerLine_meta]
            
            for j in tqdm(range(1,NumSpePerLine_meta+1), disable=True):     # grab spectrum at each scan
            
                TIC = TICs[j-1]
                pixelsPerLine_meta[j-1,0] = TIC
                
                # range for TimeStamp
                rt_lw, rt_up = TimeStamps[j-1]-0.009, TimeStamps[j-1]+0.009      ### currently hard code!
                # get peak intensity
                for k in range(MassList.shape[0]):
                    mass_lw, mass_up = MassList[k]*(1-MassTolerance*0.000001), MassList[k]*(1+MassTolerance*0.000001)
                    pixelsPerLine_meta[j-1, k+1] = data.xic(rt_lw, rt_up, mass_lw, mass_up)[0][1]            
            data.close()

        # after you have data for that line, do interpolation (including TIC)
        for l in range(pixelsPerLine.shape[1]):
            pixelsPerLine[:,l] = np.interp(TimeStamps_aligned, TimeStamps, pixelsPerLine_meta[:,l])

        # stack PixelsPerLine vertically onto total pixels
        pixels = np.append(pixels,pixelsPerLine,axis=0)
        # wrap up this line
        SpenTime = (time.time()-StaTime)        
        print("line {} is done, running time is:\n{} s\n ".format(i,round(SpenTime, 2)))

    return pixels

#==================================   raw file info extraction, with filters   ============================================
'''
Currently only work for .raw files. 
'''

def get_filters_info(NameBody, NamePost, line_idx):
    '''
    designate a line, and check filters in it. 
    output: np.arrays of Filters, acq_type and mz_ranges
    '''
    # get all filters
    Name = NameBody + str(line_idx) + NamePost
    RawFile = MSFileReader(Name)
    Filters = []
    for i in range(1, RawFile.LastSpectrumNumber+1):
        Filter = RawFile.GetFilterForScanNum(i)
        Filters.append(Filter)
    RawFile.Close()
    Filters = np.array(Filters)
    Filters = np.unique(Filters)
    
    # get acquisition types from filters by string manipulation
    # currently may have 3 types Fullms, Fullms2, SIMms
    
    acq_types = []
    for Filter in Filters:
        string = Filter.split(' ')
        acq_type = string[4] + string[5]
        acq_types.append(acq_type)
    acq_types = np.array(acq_types)
    
    # get mz ranges from filters by string manipulation, experimental
    mz_ranges = []
    for Filter in Filters:
        mz_range = []
        string = Filter.split()
        string = string[-1]
        mz_start = float(string.split('[')[-1].split(']')[0].split('-')[0])
        mz_end = float(string.split('[')[-1].split(']')[0].split('-')[1])
        mz_range.append(mz_start)
        mz_range.append(mz_end)
        mz_ranges.append(mz_range)
    mz_ranges = np.array(mz_ranges)
    return [Filters, acq_types, mz_ranges]

def get_ScansPerFilter(NameBody, NamePost, NumLine, Filters):
    '''
    Works for multi Filters.
    '''
    # accumulator
    NumLineSpe = np.empty(([0, Filters[0].shape[0]])).astype(int)

    for i in tqdm(range(1, NumLine+1)):

        # counter for a line
        Dims = np.zeros((Filters[0].shape[0])).astype(int)

        # get in the line
        Name = NameBody + str(i) +NamePost
        RawFile = MSFileReader(Name)

        for j in range(1, RawFile.LastSpectrumNumber+1):
            Filter = RawFile.GetFilterForScanNum(j)
            idx = np.where(Filter == Filters[0])[0][0]

            # count on 
            Dims[idx] += 1

        # count on
        NumLineSpe = np.append(NumLineSpe, Dims.reshape((1, Filters[0].shape[0])), axis=0)
        RawFile.Close()
    return NumLineSpe

def get_PeakCountsPerFilter(filters_info, MassList_filters, MassList_mz):
    '''
    it should work for MS1 and SIM. But may not work for MS2, which need to parse precursor?
    output: np.arrays of 1 peak_counts per filter and 2. mzs per filter
    '''
    peak_counts = np.zeros((filters_info[0].shape)).astype(int)
    mzs_per_filter = [ [] for _ in range(filters_info[0].shape[0]) ]

    # lets pass the types and then pass the mz_ranges....
    for i in range(MassList_mz.shape[0]):
        Filter = MassList_filters[i]
        mz = MassList_mz[i]

        for j in range(filters_info[0].shape[0]):
            target_filter_type = filters_info[0][j]

            # determine which filter to go for this MassList entry
            if Filter == target_filter_type:
                peak_counts[j] += 1
                mzs_per_filter[j].append(mz)
    return peak_counts, mzs_per_filter

def get_pixels_values_filter(NumLine, TimeStamp_aligned, filters_info, PeakCountsPerFilter, mzsPerFilter, ScansPerFilter):
    '''
    In peak intensity extraction:
    loop among lines:
        loop among scans:
            loop among peaks:
    In pixel alignment (interpolation) with respct to time stamp:
    loop among filters:
        loop among peaks:

    warning: a potential bug is that TimeStamps have 0 value. Check if this happens.
    '''
    pixels_total = [ np.empty([0, PeakCountsPerFilter[_] + 1]) for _ in range(filters_info[0].shape[0]) ]

    for i in range(1, NumLine+1):
        StaTime=time.time()

        Name = NameBody + str(i) + NamePost
        RawFile = MSFileReader(Name)

        # accumulators for all fitlers,for line before interpolation, interpolation: intensity, scan/acq_time
        TimeStamps = [ np.zeros((ScansPerFilter[i-1][_])) for _ in range(filters_info[0].shape[0]) ]
        # a list of 2d matrix, matrix: scans x (mzs +1)  , 1 -> tic
        pixels_meta = [ np.zeros((ScansPerFilter[i-1][_] , PeakCountsPerFilter[_] + 1)) for _ in range(filters_info[0].shape[0]) ]

        # accumulators after the interpolation
        pixels = [ np.zeros((TimeStamp_aligned.shape[0] , PeakCountsPerFilter[_] + 1)) for _ in range(filters_info[0].shape[0]) ]

        # counter to track filtered data accumulation
        counter = np.zeros((filters_info[0].shape[0])).astype(int)-1 # start from -1, +=1 before handeling

        for j in tqdm(range(1,RawFile.LastSpectrumNumber+1)):

            # return filter
            # and figure out idx for accumulator
            Filter = RawFile.GetFilterForScanNum(j)
            idx = np.where(Filter == filters_info[0])[0][0]
            counter[idx] += 1

            # return header
            header = RawFile.GetScanHeaderInfoForScanNum(j)
            TimeStamp = header['StartTime']
            TIC = header['TIC']
            # handle info
            TimeStamps[idx][counter[idx]] = TimeStamp 
            pixels_meta[idx][counter[idx], 0] = TIC


            # return spectrum
            mzlist = RawFile.GetMassListFromScanNum(j)
            mz = np.array(mzlist[0][0])
            IntensityPoints = np.array(mzlist[0][1])

            for k in range(PeakCountsPerFilter[idx]):
                target_mz = mzsPerFilter[idx][k]
                PeakPoints = IntensityPoints[(mz > target_mz*(1-MassTolerance*0.000001))&(mz < target_mz*(1+MassTolerance*0.000001))]
                Intensity = PeakPoints.sum()
                pixels_meta[idx][counter[idx], k+1] = Intensity

        RawFile.Close()

        # interpolation
        for m in range(filters_info[0].shape[0]):
            for n in range(pixels_meta[m].shape[1]):
                pixels[m][:, n] = np.interp(TimeStamps_aligned, TimeStamps[m], pixels_meta[m][:, n])
            pixels_total[m] = np.append(pixels_total[m], pixels[m], axis=0)

        SpenTime = (time.time()-StaTime)        
        print("\nline {} is done, running time is:\n{}\n ".format(i,SpenTime))
    return pixels_total


def show_ms1_imgs(imgs, MassList, includes_TIC = False, scale = .999, aspect = 1, cmap = 'viridis', savefig = False, savedir = ''):
    if not savedir:
        raise ValueError('savedir must be a path')
    
    savedir = os.path.join(savedir,'images')
    if not os.path.isdir(savedir):
        os.mkdir(savedir)
    
    for i in tqdm(range(imgs.shape[-1])):     # edit
        img = imgs[:,:,i]
        thre = np.quantile(img, scale)
        if includes_TIC:
            if i == 0:
                title = 'TIC'
            else:
                title = 'm/z ' + str((MassList[i-1]))
        else:
            title = 'm/z ' + str((MassList[i]))
        plt.figure(figsize=(6,4))
        plot = plt.imshow(img, cmap=cmap, aspect=aspect, vmax=thre)

        plt.title(title)
        plt.xticks([])
        plt.yticks([])
        plt.colorbar()
        
        if savefig:
            plt.savefig(os.path.join(savedir,"{}.png".format(title).replace("/","")))

        plt.show()
        plt.close()