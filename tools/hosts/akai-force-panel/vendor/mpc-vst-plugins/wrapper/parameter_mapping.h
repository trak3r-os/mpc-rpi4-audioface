#pragma once
#include <math.h>

/* Used only at parameter-set/readback rate. Engine state remains physical Hz
 * and legacy waveform IDs; normalized UI order can differ without changing it. */
static inline float parameter_to_physical(const param_t *p,float n) {
    if(p->nopts) {
        // These enum positions are bounded and nonnegative: truncation after
        // +.5 has exactly lroundf's result without an ARM libm call.
        int option=(int)(n*(p->nopts-1)+.5f);
        return (float)(p->enum_values ? p->enum_values[option] : option);
    }
    if(p->logarithmic) {
        if(n<=0)return p->min;
        if(n>=1)return p->max;
        return expf(p->log_min+n*p->log_span);
    }
    return p->min+(p->max-p->min)*n;
}
static inline float parameter_to_normalized(const param_t *p,float value) {
    if(p->nopts>1) {
        if(p->enum_values) {
            const int physical=(int)(value+.5f);
            for(int i=0;i<p->nopts;++i)if(p->enum_values[i]==physical)return (float)i/(p->nopts-1);
            return 0;
        }
        return value/(p->nopts-1);
    }
    if(p->logarithmic) {
        if(value<=p->min)return 0;
        if(value>=p->max)return 1;
        return (logf(value)-p->log_min)/p->log_span;
    }
    return p->max>p->min ? (value-p->min)/(p->max-p->min) : 0;
}
