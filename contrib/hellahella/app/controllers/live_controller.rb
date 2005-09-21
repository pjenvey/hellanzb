class LiveController < ApplicationController
  before_filter :authorize, :defaults
  before_filter :load_queue, :except => :status
  before_filter :load_status, :except => :update_order

  def status
    render :partial => "status", :locals => { :status => @status }
  end

  def toggle_download
    if @status["is_paused"]
      server.call('continue')
    else
      server.call('pause')
    end
    
    # FIXME: calling this function screws up the output returned to javascript
    # (AJAX). Doing it manually
    #get_status_queue(:force => true)
    
    session[:cache].merge!({:status => server.call("status"),
                             :queuelist => server.call('list'),
                             :time => Time.at(Time.now+4)})
    
    render_text "new Ajax.Updater('hellastatus', '/live/status', {asynchronous:true, evalScripts:true})"
  end

  def enqueue_nzb
    if params[:newzbinid] =~ /^[0-9]{4,10}$/
      server.call('enqueuenewzbin', params[:newzbinid])
      render :partial => "enqueue_success"
    else
      render :partial => "enqueue_failure"
    end
  end
end
