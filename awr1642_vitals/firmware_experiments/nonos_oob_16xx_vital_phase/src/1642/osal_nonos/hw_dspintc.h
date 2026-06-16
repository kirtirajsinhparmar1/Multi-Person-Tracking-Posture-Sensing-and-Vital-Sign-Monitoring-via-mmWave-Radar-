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

/*
 *  Redistribution and use in source and binary forms, with or without
 *  modification, are permitted provided that the following conditions
 *  are met:
 *
 *    Redistributions of source code must retain the above copyright
 *    notice, this list of conditions and the following disclaimer.
 *
 *    Redistributions in binary form must reproduce the above copyright
 *    notice, this list of conditions and the following disclaimer in the
 *    documentation and/or other materials provided with the
 *    distribution.
 *
 *    Neither the name of Texas Instruments Incorporated nor the names of
 *    its contributors may be used to endorse or promote products derived
 *    from this software without specific prior written permission.
 *
 *  THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
 *  "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
 *  LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR
 *  A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT
 *  OWNER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL,
 *  SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT
 *  LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE,
 *  DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY
 *  THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
 *  (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
 *  OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
 *
 */


#ifndef HW_DSPINTC_H_
#define HW_DSPINTC_H_

#ifdef __cplusplus
extern "C"
{
#endif

/******************************************************************************
**                      DSP INTC REGISTER OFFSETS
******************************************************************************/
/**
 * \brief    Macros used in conjunction with DSP interrupt controller
 *            base address for register addressing
 *
 * \param    n - Register instance
 *
 * \note    Minimum unit = 1 byte; Registers are 4 bytes
 */
#define DSPINTC_EVTFLAG(n)  (0x00000 + ((n)*4))
#define DSPINTC_EVTSET(n)   (0x00020 + ((n)*4))
#define DSPINTC_EVTCLR(n)   (0x00040 + ((n)*4))
#define DSPINTC_EVTMASK(n)  (0x00080 + ((n)*4))
#define DSPINTC_MEVTFLAG(n) (0x000A0 + ((n)*4))
#define DSPINTC_EXPMASK(n)  (0x000C0 + ((n)*4))
#define DSPINTC_MEXPFLAG(n) (0x000E0 + ((n)*4))
#define DSPINTC_INTMUX(n)   (0x00100 + ((n)*4))
#define DSPINTC_INTXSTAT    (0x00180)
#define DSPINTC_INTXCLR     (0x00184)
#define DSPINTC_INTDMASK    (0x00188)
#define DSPINTC_AEGMUX(n)   (0x10140 + ((n)*4))


/******************************************************************************
**                      FIELD DEFINITION MACROS
******************************************************************************/
/**
 * \registers    EVENT REGISTERS
 *
 * \brief        These registers manage the system events that are received by
 *                the controller. These include flag, set, and clear registers
 *                covering all system events.
 *
 * \param        n - Any system event
 *
 * \note        Shifting by (n & 31) ensures 0x1 does not shift by more than
 *                31 bits for system event IDs larger than 31. The proper event
 *                register must first be identified.
 */

/* Event Flag */
#define DSPINTC_EVTFLAG_EF(n) (0x1 << ((n)&31))

/* Event Set */
#define DSPINTC_EVTSET_ES(n) (0x1 << ((n)&31))

/* Event Clear */
#define DSPINTC_EVTCLR_EC(n) (0x1 << ((n)&31))


/**
 * \registers    EVENT COMBINER REGISTERS
 *
 * \brief        These registers allow up to 32 events to be combined into a
 *                single combined event which can then be used by the interrupt
 *                selector.
 *
 * \param        n - Any system event
 *
 * \note        Shifting by (n & 31) ensures 0x1 does not shift by more than
 *                31 bits for system event IDs larger than 31. The proper event
 *                combiner register must first be identified.
 */

/* Event Mask */
#define DSPINTC_EVTMASK_EM(n) (0x1 << ((n)&31))

/* Masked Event Flag */
#define DSPINTC_MEVTFLAG_MEF(n) (0x1 << ((n)&31))


/**
 * \registers    CPU INTERRUPT SELECTOR REGISTERS
 *
 * \brief        These registers manage which system events trigger the
 *                available CPU interrupts and also provide interrupt exception
 *                information.
 *
 * \param        n - Any CPU maskable interrupt
 */

/* Interrupt Mux */
#define DSPINTC_INTMUX_INTSEL_SHIFT(n) (((n)&0x3) * 8)
#define DSPINTC_INTMUX_INTSEL(n)       (0x7F << DSPINTC_INTMUX_INTSEL_SHIFT(n))

/* Interrupt Exception Status */
#define DSPINTC_INTXSTAT_SYSINT       (0xFF000000u)
#define DSPINTC_INTXSTAT_SYSINT_SHIFT (0x00000018u)
#define DSPINTC_INTXSTAT_CPUINT       (0x00FF0000u)
#define DSPINTC_INTXSTAT_CPUINT_SHIFT (0x00000010u)
#define DSPINTC_INTXSTAT_DROP         (0x00000001u)
#define DSPINTC_INTXSTAT_DROP_SHIFT   (0x00000000u)

/* Interrupt Exception Clear */
#define DSPINTC_INTXCLR_CLEAR       (0x00000001u)
#define DSPINTC_INTXCLR_CLEAR_SHIFT (0x00000000u)

/* Dropped Interrupt Mask */
#define DSPINTC_INTDMASK_IDM(n) (0x1 << (n))


    /**
     * \registers    CPU EXCEPTION REGISTERS
     *
     * \brief
     *
     * \param
     *
     * \note        Not yet defined...
     */

    /**
     * \registers    ADVANCED EVENT GENERATOR MUX REGISTERS
     *
     * \brief
     *
     * \param
     *
     * \note        Not yet defined...
     */

#ifdef __cplusplus
}
#endif

#endif /* HW_DSPINTC_H_ */
