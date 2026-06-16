/*
* Copyright (C) 2024 Texas Instruments Incorporated
*
* All rights reserved not granted herein.
* Limited License.  
*
* Texas Instruments Incorporated grants a world-wide, royalty-free, 
* non-exclusive license under copyrights and patents it now or hereafter 
* owns or controls to make, have made, use, import, offer to sell and sell ("Utilize")
* this software subject to the terms herein.  With respect to the foregoing patent 
* license, such license is granted  solely to the extent that any such patent is necessary 
* to Utilize the software alone.  The patent license shall not apply to any combinations which 
* include this software, other than combinations with devices manufactured by or for TI ("TI Devices").  
* No hardware patent is licensed hereunder.
*
* Redistributions must preserve existing copyright notices and reproduce this license (including the 
* above copyright notice and the disclaimer and (if applicable) source code license limitations below) 
* in the documentation and/or other materials provided with the distribution
*
* Redistribution and use in binary form, without modification, are permitted provided that the following
* conditions are met:
*
*	* No reverse engineering, decompilation, or disassembly of this software is permitted with respect to any 
*     software provided in binary form.
*	* any redistribution and use are licensed by TI for use only with TI Devices.
*	* Nothing shall obligate TI to provide you with source code for the software licensed and provided to you in object code.
*
* If software source code is provided to you, modification and redistribution of the source code are permitted 
* provided that the following conditions are met:
*
*   * any redistribution and use of the source code, including any resulting derivative works, are licensed by 
*     TI for use only with TI Devices.
*   * any redistribution and use of any object code compiled from the source code and any resulting derivative 
*     works, are licensed by TI for use only with TI Devices.
*
* Neither the name of Texas Instruments Incorporated nor the names of its suppliers may be used to endorse or 
* promote products derived from this software without specific prior written permission.
*
* DISCLAIMER.
*
* THIS SOFTWARE IS PROVIDED BY TI AND TI'S LICENSORS "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, 
* BUT NOT LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE DISCLAIMED. 
* IN NO EVENT SHALL TI AND TI'S LICENSORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR 
* CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, 
* OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, 
* OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE 
* POSSIBILITY OF SUCH DAMAGE.
*/


#ifndef REG_VIM_H
#define REG_VIM_H

#include <stdint.h>

#ifdef __cplusplus
extern "C"
{
#endif

    /* Vim Register Frame Definition */
    /** @struct vimBase
     *   @brief Vim Register Frame Definition
     *
     *   This type is used to access the Vim Registers.
     */
    /** @typedef vimBASE_t
     *   @brief VIM Register Frame Type Definition
     *
     *   This type is used to access the VIM Registers.
     */
    typedef volatile struct vimBase
    {
        uint32_t IRQINDEX; /* 0x0000       */
        uint32_t FIQINDEX; /* 0x0004       */
        uint32_t rsvd1; /* 0x0008       */
        uint32_t rsvd2; /* 0x000C       */
        uint32_t FIRQPR0; /* 0x0010       */
        uint32_t FIRQPR1; /* 0x0014       */
        uint32_t FIRQPR2; /* 0x0018       */
        uint32_t FIRQPR3; /* 0x001C       */
        uint32_t INTREQ0; /* 0x0020       */
        uint32_t INTREQ1; /* 0x0024       */
        uint32_t INTREQ2; /* 0x0028       */
        uint32_t INTREQ3; /* 0x002C       */
        uint32_t REQMASKSET0; /* 0x0030       */
        uint32_t REQMASKSET1; /* 0x0034       */
        uint32_t REQMASKSET2; /* 0x0038       */
        uint32_t REQMASKSET3; /* 0x003C       */
        uint32_t REQMASKCLR0; /* 0x0040       */
        uint32_t REQMASKCLR1; /* 0x0044       */
        uint32_t REQMASKCLR2; /* 0x0048       */
        uint32_t REQMASKCLR3; /* 0x004C       */
        uint32_t WAKEMASKSET0; /* 0x0050       */
        uint32_t WAKEMASKSET1; /* 0x0054       */
        uint32_t WAKEMASKSET2; /* 0x0058       */
        uint32_t WAKEMASKSET3; /* 0x005C       */
        uint32_t WAKEMASKCLR0; /* 0x0060       */
        uint32_t WAKEMASKCLR1; /* 0x0064       */
        uint32_t WAKEMASKCLR2; /* 0x0068       */
        uint32_t WAKEMASKCLR3; /* 0x006C       */
        uint32_t IRQVECREG; /* 0x0070       */
        uint32_t FIQVECREG; /* 0x0074       */
        uint32_t CAPEVT; /* 0x0078       */
        uint32_t rsvd3; /* 0x007C       */
        uint32_t CHANCTRL[16U]; /* 0x0080-0x0BC */
    } vimBASE_t;

#define vimREG ((vimBASE_t *)0xFFFFFE00U)

#ifdef __cplusplus
}
#endif

#endif
